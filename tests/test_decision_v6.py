import copy
import json
import math
import unittest

from orgbench.decision_v6 import analyze_confirm, REQUIRED_FIELDS


def cells(n=18, *, candidate="contract_team", primary=False, secondary=False,
          candidate_success=True, repeats=1, candidate_tokens=100, control_tokens=200):
    rows = []
    arms = (candidate, "single_self_review", "single_tool", "hierarchy_tool", "best_of_three")
    for task in range(n):
        for arm in arms:
            success = candidate_success if arm == candidate else primary if arm == "single_self_review" else secondary
            tokens = candidate_tokens if arm == candidate else control_tokens
            for repeat in range(repeats):
                rows.append({"task_id": f"t{task}", "family": f"family_{task % 3}",
                             "architecture": arm, "repeat": repeat, "status": "ok",
                             "evaluation": {"success": bool(success), "score": float(success)},
                             "input_tokens": tokens // 2, "output_tokens": tokens - tokens // 2,
                             "cache_read_input_tokens": 0, "calls": 1, "wall_s": 1.,
                             "usage_complete": True, "actual_input_budget_exceeded": False,
                             "actual_output_budget_exceeded": False,
                             "budget": {"max_calls": 5, "max_input_tokens": 32000, "max_output_tokens": 12000}})
    return rows


class DecisionV6Tests(unittest.TestCase):
    def decide(self, rows, **kwargs):
        return analyze_confirm(rows, candidate=kwargs.pop("candidate", "contract_team"),
                               expected_tasks=kwargs.pop("expected_tasks", 18), draws=120, **kwargs)

    def assert_no_claims(self, result):
        self.assertFalse(result["valid_for_confirmation"])
        self.assertFalse(result["confirmed_primary_quality_improvement"])
        self.assertFalse(any(result["confirmed_secondary_quality_improvements"].values()))

    def test_complete_positive_primary_and_three_secondary(self):
        result = self.decide(cells())
        self.assertTrue(result["complete"])
        self.assertTrue(result["valid_for_confirmation"])
        self.assertTrue(result["confirmed_primary_quality_improvement"])
        self.assertTrue(all(result["confirmed_secondary_quality_improvements"].values()))
        self.assertEqual(result["primary_comparison"]["family_alpha"], .025)
        self.assertEqual(result["primary_comparison"]["permutation_method"], "exact_integer_dp_task_sign_permutation")
        for comparison in result["secondary_comparisons_holm_family_of_three"].values():
            self.assertEqual(3, comparison["holm_family_size"])
            self.assertEqual(.025, comparison["family_alpha"])
        json.dumps(result, allow_nan=False)

    def test_primary_is_not_required_to_beat_all_secondary(self):
        result = self.decide(cells(secondary=True))
        self.assertTrue(result["confirmed_primary_quality_improvement"])
        self.assertFalse(any(result["confirmed_secondary_quality_improvements"].values()))
        self.assertFalse(result["must_win_all_controls"])

    def test_secondary_can_win_when_primary_ties(self):
        result = self.decide(cells(primary=True))
        self.assertFalse(result["confirmed_primary_quality_improvement"])
        self.assertTrue(all(result["confirmed_secondary_quality_improvements"].values()))

    def test_zero_quality_difference_does_not_claim_improvement(self):
        for value in (True, False):
            result = self.decide(cells(primary=value, secondary=value, candidate_success=value))
            self.assertTrue(result["valid_for_confirmation"])
            self.assertEqual(0., result["primary_comparison"]["delta"])
            self.assertEqual(1., result["primary_comparison"]["p_two_sided"])
            self.assertFalse(result["confirmed_primary_quality_improvement"])
            self.assertFalse(any(result["confirmed_secondary_quality_improvements"].values()))

    def test_repetitions_are_not_extra_tasks(self):
        result = self.decide(cells(repeats=2), expected_repeats=2)
        self.assertEqual(180, result["expected_cells"])
        self.assertEqual(18, result["primary_comparison"]["tasks"])
        self.assertTrue(result["confirmed_primary_quality_improvement"])

    def test_precise_expected_ids_and_missing_cells(self):
        ids = {f"t{i}" for i in range(18)}
        result = self.decide(cells()[:-1], expected_tasks=ids)
        self.assert_no_claims(result)
        self.assertEqual(1, result["validation"]["missing_cell_count"])
        self.assertIn("missing_cells", result["decision_blockers"])

    def test_duplicate_cell_invalidates_even_if_grid_is_covered(self):
        rows = cells()
        rows.append(copy.deepcopy(rows[0]))
        result = self.decide(rows)
        self.assert_no_claims(result)
        self.assertEqual(1, result["validation"]["duplicate_cell_count"])

    def test_unexpected_arm_or_task_is_not_silently_ignored(self):
        for kind in ("architecture", "task_id"):
            rows = cells()
            extra = copy.deepcopy(rows[0])
            extra[kind] = "unexpected"
            rows.append(extra)
            result = self.decide(rows, expected_tasks={f"t{i}" for i in range(18)})
            self.assert_no_claims(result)
            self.assertEqual(1, result["validation"]["unexpected_cell_count"])

    def test_bad_candidate_or_control_collision(self):
        for candidate in ("typo_candidate", "single_tool", "single_self_review", None):
            result = self.decide(cells(), candidate=candidate)
            self.assert_no_claims(result)
            self.assertIn("unsupported_candidate", result["decision_blockers"])

    def test_missing_fixed_field_is_explicit(self):
        for field in REQUIRED_FIELDS:
            rows = cells()
            target = rows[0]
            parts = field.split(".")
            for part in parts[:-1]:
                target = target[part]
            del target[parts[-1]]
            with self.subTest(field=field):
                result = self.decide(rows)
                self.assert_no_claims(result)
                self.assertTrue(any("missing_field:" + field in e["reasons"] for e in result["validation"]["row_errors"]))

    def test_unknown_usage_any_arm_blocks_all_claims(self):
        for index in range(5):
            rows = cells()
            rows[index]["usage_complete"] = False
            result = self.decide(rows)
            self.assert_no_claims(result)
            self.assertTrue(result["complete"])
            self.assertEqual(1, result["unknown_usage_cells"])
            self.assertIn("unknown_usage", result["decision_blockers"])

    def test_infrastructure_and_nested_executor_error_block_claims(self):
        for nested in (False, True):
            rows = cells()
            if nested:
                rows[1]["evaluation"]["executor_infrastructure_error"] = True
            else:
                rows[1]["status"] = "evaluator_error"
            result = self.decide(rows)
            self.assert_no_claims(result)
            self.assertEqual(1, result["infrastructure_cells"])

    def test_resource_overrun_flags_or_observed_caps_block_all(self):
        mutations = (("actual_input_budget_exceeded", True), ("actual_output_budget_exceeded", True),
                     ("input_tokens", 32001), ("output_tokens", 12001), ("calls", 6))
        for field, value in mutations:
            rows = cells()
            rows[3][field] = value
            result = self.decide(rows)
            self.assert_no_claims(result)
            self.assertEqual(1, result["actual_overrun_cells"])

    def test_budget_exhaustion_inside_caps_is_a_legal_failure(self):
        rows = cells()
        rows[1]["status"] = "budget_exhausted"
        result = self.decide(rows)
        self.assertTrue(result["valid_for_confirmation"])
        self.assertTrue(result["confirmed_primary_quality_improvement"])

    def test_inconsistent_budget_and_family_are_invalid(self):
        for field in ("budget", "family"):
            rows = cells()
            if field == "budget": rows[1]["budget"]["max_calls"] = 6
            else: rows[1]["family"] = "different_family"
            result = self.decide(rows)
            self.assert_no_claims(result)

    def test_nonfinite_tokens_and_boolean_counts_are_invalid(self):
        for field, value in (("input_tokens", math.nan), ("calls", True), ("wall_s", math.inf),
                             ("cache_read_input_tokens", -1), ("usage_complete", None)):
            rows = cells()
            rows[0][field] = value
            result = self.decide(rows)
            self.assert_no_claims(result)
            self.assertTrue(result["validation"]["row_errors"])

    def test_exact_ids_reject_balanced_replacement(self):
        rows = cells()
        for row in rows:
            if row["task_id"] == "t0": row["task_id"] = "replacement"
        result = self.decide(rows, expected_tasks={f"t{i}" for i in range(18)})
        self.assert_no_claims(result)
        self.assertEqual(5, result["validation"]["unexpected_cell_count"])
        self.assertEqual(5, result["validation"]["missing_cell_count"])

    def test_token_ratios_are_only_descriptive(self):
        result = self.decide(cells(primary=True, secondary=True))
        token = result["primary_comparison"]["token_ratio"]
        self.assertEqual(.5, token["ratio"])
        self.assertEqual([.5, .5], token["ci95"])
        self.assertTrue(token["descriptive_only"])
        self.assertNotIn("confirmed_efficiency_improvement", result)

    def test_zero_cost_has_no_infinite_json(self):
        result = self.decide(cells(candidate_tokens=0, control_tokens=0))
        self.assertIsNone(result["primary_comparison"]["token_ratio"]["ratio"])
        self.assertEqual("zero_baseline_tokens", result["primary_comparison"]["token_ratio"]["unavailable_reason"])
        json.dumps(result, allow_nan=False)

    def test_family_outputs_are_exploratory(self):
        result = self.decide(cells())
        self.assertEqual(3, len(result["family_exploratory"]))
        for family in result["family_exploratory"].values():
            self.assertTrue(family["descriptive_only"])
            self.assertTrue(family["no_confirmatory_subgroup_claims"])
            self.assertEqual(6, family["independent_tasks"])
            self.assertEqual(4, len(family["unadjusted_exploratory_paired_comparisons"]))

    def test_invalidated_study_is_blocked(self):
        rows = cells()
        rows[0]["invalidated"] = True
        result = self.decide(rows)
        self.assert_no_claims(result)
        self.assertTrue(result["invalidated"])

    def test_bad_configuration_is_not_silently_defaulted(self):
        for expected in (0, -1, True, None, "t0", [], ["t0", "t0"]):
            with self.subTest(expected=expected), self.assertRaises((ValueError, TypeError)):
                self.decide([], expected_tasks=expected)
        with self.assertRaises(ValueError):
            self.decide(cells(), expected_repeats=0)


if __name__ == "__main__":
    unittest.main()
