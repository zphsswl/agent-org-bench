import copy
import json
import math
import unittest

from orgbench.decision import analyze_confirm, clopper_pearson_upper, _binomial_cdf


def cells(n, candidate_success=True, baseline_success=True, secondary_success=True,
          candidate_tokens=100, baseline_tokens=200, repeats=1):
    rows = []
    for task in range(n):
        for architecture, success, tokens in (("candidate", candidate_success, candidate_tokens),
                                               ("single_tool", baseline_success, baseline_tokens),
                                               ("hierarchy_tool", secondary_success, baseline_tokens * 2)):
            for repetition in range(repeats):
                rows.append({"task_id": f"t{task}", "family": f"family{task % 3}",
                             "architecture": architecture, "repeat": repetition,
                             "evaluation": {"success": success, "score": float(success)},
                             "input_tokens": tokens // 2, "output_tokens": tokens - tokens // 2,
                             "wall_s": 1., "status": "ok", "usage_complete": True})
    return rows


class DecisionTests(unittest.TestCase):
    def decide(self, rows, **kwargs):
        return analyze_confirm(rows, "candidate", bootstrap_draws=200, **kwargs)

    def test_cp_zero_losses_n90_is_not_zero(self):
        bound = clopper_pearson_upper(0, 90)
        self.assertAlmostEqual(bound, 1 - .025 ** (1 / 90), places=12)
        self.assertGreater(bound, .04)
        self.assertLess(bound, .05)

    def test_cp_small_sample_cannot_establish_5pp_noninferiority(self):
        self.assertGreater(clopper_pearson_upper(0, 9), .05)
        self.assertEqual(clopper_pearson_upper(0, 0), 1.)
        self.assertEqual(clopper_pearson_upper(9, 9), 1.)

    def test_cp_nonboundary_inverts_binomial_cdf(self):
        upper = clopper_pearson_upper(3, 90)
        self.assertAlmostEqual(_binomial_cdf(3, 90, upper), .025, places=11)
        self.assertGreater(upper, 3 / 90)

    def test_cp_probability_boundaries_and_validation(self):
        self.assertEqual(_binomial_cdf(0, 5, 0), 1.)
        self.assertEqual(_binomial_cdf(0, 5, 1), 0.)
        for args in ((-1, 9), (10, 9), (0, -1), (True, 9)):
            with self.assertRaises(ValueError):
                clopper_pearson_upper(*args)

    def test_efficiency_passes_with_90_no_loss_and_half_cost(self):
        result = self.decide(cells(90), expected_tasks=90)
        self.assertTrue(result["complete"])
        self.assertTrue(result["valid_for_confirmation"])
        self.assertTrue(result["confirmed_efficiency_improvement"])
        self.assertFalse(result["confirmed_quality_improvement_vs_all_baselines"])
        self.assertEqual(result["efficiency"]["tokens"]["ci95"], [.5, .5])
        self.assertEqual(result["fwer_allocation"]["quality_holm_two"], .025)
        json.dumps(result, allow_nan=False)

    def test_zero_differences_do_not_establish_small_sample_noninferiority(self):
        result = self.decide(cells(9), expected_tasks=9)
        self.assertFalse(result["confirmed_efficiency_improvement"])
        self.assertFalse(result["efficiency"]["quality_noninferiority_passed"])

    def test_all_failed_cheaper_candidate_cannot_claim_efficiency(self):
        result = self.decide(cells(90, candidate_success=False, baseline_success=False,
                                  secondary_success=False), expected_tasks=90)
        self.assertTrue(result["efficiency"]["quality_noninferiority_passed"])
        self.assertTrue(result["efficiency"]["token_saving_passed"])
        self.assertEqual(result["efficiency"]["candidate_observed_success_rate"], 0.)
        self.assertFalse(result["efficiency"]["usability_gate_passed"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_efficiency_usability_floor_includes_exactly_half_success(self):
        rows = cells(90)
        for row in rows:
            row["evaluation"]["success"] = int(row["task_id"][1:]) < 45
        result = self.decide(rows, expected_tasks=90)
        self.assertEqual(result["efficiency"]["candidate_observed_success_rate"], .5)
        self.assertEqual(result["efficiency"]["baseline_observed_success_rate"], .5)
        self.assertTrue(result["efficiency"]["usability_gate_passed"])
        self.assertTrue(result["confirmed_efficiency_improvement"])

    def test_below_half_success_is_not_usable_even_if_equal_and_cheaper(self):
        rows = cells(90)
        for row in rows:
            row["evaluation"]["success"] = int(row["task_id"][1:]) < 44
        result = self.decide(rows, expected_tasks=90)
        self.assertLess(result["efficiency"]["candidate_observed_success_rate"], .5)
        self.assertFalse(result["efficiency"]["usability_gate_passed"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_low_baseline_usability_does_not_block_real_quality_superiority(self):
        result = self.decide(cells(90, baseline_success=False, secondary_success=False), expected_tasks=90)
        self.assertTrue(result["confirmed_quality_improvement_vs_all_baselines"])
        self.assertFalse(result["efficiency"]["usability_gate_passed"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_repetitions_cannot_inflate_independent_n(self):
        result = self.decide(cells(9, repeats=10), expected_tasks=9, expected_repeats=10)
        self.assertTrue(result["complete"])
        self.assertEqual(result["efficiency"]["tasks"], 9)
        self.assertEqual(result["quality_comparisons_holm_family_of_two"]["single_tool"]["tasks"], 9)
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_quality_superiority_uses_two_baselines_and_family_alpha(self):
        result = self.decide(cells(12, baseline_success=False, secondary_success=False), expected_tasks=12)
        self.assertTrue(result["confirmed_quality_improvement_vs_all_baselines"])
        for comparison in result["quality_comparisons_holm_family_of_two"].values():
            self.assertEqual(comparison["family_alpha"], .025)
            self.assertLess(comparison["p_holm"], .025)
        self.assertEqual(result["efficiency"]["family_alpha"], .025)

    def test_quality_does_not_claim_when_only_secondary_is_beaten(self):
        result = self.decide(cells(12, secondary_success=False), expected_tasks=12)
        self.assertFalse(result["confirmed_quality_improvement_vs_all_baselines"])
        self.assertFalse(result["quality_comparisons_holm_family_of_two"]["single_tool"]["confirmed_quality_improvement"])

    def test_quality_losses_block_efficiency_even_if_cheaper(self):
        rows = cells(90)
        for row in rows:
            if row["architecture"] == "candidate" and int(row["task_id"][1:]) < 10:
                row["evaluation"]["success"] = False
        result = self.decide(rows, expected_tasks=90)
        self.assertEqual(result["efficiency"]["loss_tasks"], 10)
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_cost_reduction_strictly_exceeds_15_percent(self):
        result = self.decide(cells(90, candidate_tokens=170, baseline_tokens=200), expected_tasks=90)
        self.assertFalse(result["confirmed_efficiency_improvement"])
        self.assertFalse(result["efficiency"]["token_saving_passed"])

    def test_incomplete_grid_disables_all_claims(self):
        rows = cells(12, baseline_success=False, secondary_success=False)
        result = self.decide(rows[:-1], expected_tasks=12)
        self.assertFalse(result["complete"])
        self.assertFalse(result["confirmed_quality_improvement_vs_all_baselines"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_duplicate_cannot_fake_completeness(self):
        rows = cells(90)
        rows[-1] = copy.deepcopy(rows[0])
        result = self.decide(rows, expected_tasks=90)
        self.assertFalse(result["complete"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_exact_expected_ids_guard_wrong_task_set(self):
        result = self.decide(cells(90), expected_tasks=[f"other{i}" for i in range(90)])
        self.assertFalse(result["complete"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_no_planned_count_cannot_confirm(self):
        result = self.decide(cells(90))
        self.assertFalse(result["complete"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_invalidated_study_forbids_claims(self):
        result = self.decide(cells(90), expected_tasks=90, invalidated=True)
        self.assertTrue(result["complete"])
        self.assertFalse(result["valid_for_confirmation"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_infrastructure_contamination_forbids_claims(self):
        rows = cells(90)
        rows[0]["status"] = "provider_error"
        result = self.decide(rows, expected_tasks=90)
        self.assertEqual(result["infrastructure_errors"], 1)
        self.assertFalse(result["valid_for_confirmation"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_success_on_incomplete_execution_cannot_be_counted_as_confirmation(self):
        rows = cells(90)
        rows[0]["status"] = "budget_exhausted"
        result = self.decide(rows, expected_tasks=90)
        self.assertFalse(result["complete"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_unknown_usage_blocks_efficiency_but_not_clean_quality(self):
        rows = cells(12, baseline_success=False, secondary_success=False)
        rows[0]["usage_complete"] = False
        result = self.decide(rows, expected_tasks=12)
        self.assertTrue(result["confirmed_quality_improvement_vs_all_baselines"])
        self.assertFalse(result["efficiency"]["usage_complete"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_missing_or_invalid_cost_never_confirms_efficiency(self):
        for value in (None, -1, math.nan):
            rows = cells(90)
            rows[0]["output_tokens"] = value
            result = self.decide(rows, expected_tasks=90)
            self.assertFalse(result["efficiency"]["usage_complete"])
            self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_no_rows_is_safe_and_not_certain(self):
        result = self.decide([], expected_tasks=90)
        self.assertFalse(result["valid_for_confirmation"])
        self.assertEqual(result["efficiency"]["loss_probability_upper_one_sided_97_5"], 1.)
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_observed_frontier_is_explicitly_descriptive(self):
        result = self.decide(cells(9), expected_tasks=9)
        self.assertTrue(result["observed_pareto"]["descriptive_only"])
        self.assertTrue(result["observed_pareto"]["architectures"]["candidate"]["on_observed_pareto_frontier"])
        self.assertFalse(result["confirmed_efficiency_improvement"])

    def test_zero_baseline_cost_never_proves_saving(self):
        result = self.decide(cells(90, candidate_tokens=0, baseline_tokens=0), expected_tasks=90)
        self.assertIsNone(result["efficiency"]["tokens"]["ratio"])
        self.assertFalse(result["confirmed_efficiency_improvement"])
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
