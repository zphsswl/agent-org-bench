"""Organization tests use real toy public-example feedback, never model judges."""
from __future__ import annotations

import ast
import copy
import json
import unittest

from orgbench.tool_organizations import (DESCRIPTIONS, public_route_features,
                                         run_tool_organization)


GOOD = 'def solve(payload):\n    return {"n": payload["n"]}\n'
SEVEN = 'def solve(payload):\n    return {"n": 7}\n'
EIGHT = 'def solve(payload):\n    return {"n": 8}\n'
BAD = 'def solve(payload):\n    return {"n": 99}\n'


class PrivateTrap:
    def __repr__(self):
        raise AssertionError("Hidden test data was touched")

    def __deepcopy__(self, memo):
        raise AssertionError("Hidden test data was copied")


def problem(spec="Return n unchanged.", rules=None):
    return {"id": "toy-code", "family": "do_not_route_on_this",
            "prompt": "Write solve(payload) returning {'n': payload['n']}. No imports.",
            "schema": {"source": "Python solve(payload) source"},
            "public": {"spec": spec, "rules": {} if rules is None else rules,
                       "examples": [{"payload": {"n": value}, "expected": {"n": value}}
                                    for value in (7, 8, 9)],
                       "function": "solve(payload)", "allowed_python_subset": "def, return, dict, subscript"},
            "private": PrivateTrap()}


class ToyPublicValidator:
    """A tiny AST-only external tool for this fixture; no exec/eval is used."""
    def __init__(self):
        self.calls = []

    def __call__(self, task, answer):
        if "private" in task:
            raise AssertionError("Hidden evaluator data crossed public boundary")
        self.calls.append({"source": answer.get("source"), "examples": copy.deepcopy(task["public"]["examples"])})
        total = len(task["public"]["examples"])
        try:
            tree = ast.parse(answer["source"])
            function = tree.body[0]
            if not isinstance(function, ast.FunctionDef) or function.name != "solve":
                raise ValueError("missing solve")
            statement = function.body[0]
            if not isinstance(statement, ast.Return):
                raise ValueError("unsupported statement")

            def expression(node, payload):
                if isinstance(node, ast.Constant):
                    return node.value
                if isinstance(node, ast.Dict):
                    return {expression(key, payload): expression(value, payload)
                            for key, value in zip(node.keys, node.values)}
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "payload":
                    return payload[expression(node.slice, payload)]
                raise ValueError("unsupported expression")

            passed = 0
            violations = []
            for index, case in enumerate(task["public"]["examples"]):
                got = expression(statement.value, case["payload"])
                if got == case["expected"]:
                    passed += 1
                else:
                    violations.append(f"public example {index}: expected {case['expected']}, got {got}")
            return {"success": passed == total, "score": passed / total,
                    "valid_syntax": True, "public_passed": passed,
                    "public_total": total, "violations": violations}
        except Exception as exc:
            return {"success": False, "score": 0.0, "valid_syntax": False,
                    "public_passed": 0, "public_total": total,
                    "violations": ["syntax or supported-subset failure: " + type(exc).__name__]}


class StubProvider:
    def __init__(self, responses, *, use_full_allowance=False, fail_at=None):
        self.responses = responses
        self.requests = []
        self.use_full_allowance = use_full_allowance
        self.fail_at = fail_at

    def complete(self, system, prompt, max_tokens=None):
        index = len(self.requests)
        self.requests.append({"system": system, "prompt": prompt, "max_tokens": max_tokens})
        if index == self.fail_at:
            raise RuntimeError("must-not-copy-credential-token")
        response = self.responses[min(index, len(self.responses) - 1)]
        return {"text": response if isinstance(response, str) else json.dumps(response),
                "input_tokens": 101, "cache_read_input_tokens": 21,
                "output_tokens": max_tokens if self.use_full_allowance else 17,
                "model": "same-test-model", "latency_s": 0.01}


def source(code):
    return {"source": code}


class ToolOrganizationTests(unittest.TestCase):
    def execute(self, name, responses, **kwargs):
        validator = kwargs.pop("validator", ToyPublicValidator())
        provider = kwargs.pop("provider", StubProvider(responses))
        task = kwargs.pop("task", problem())
        outcome = run_tool_organization(name, task, provider, public_validator=validator, **kwargs)
        return outcome, provider, validator

    def test_strong_single_uses_full_first_allowance_and_stops_on_real_public_pass(self):
        outcome, provider, validator = self.execute("single_tool", [source(GOOD)])
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["calls"], 1)
        self.assertEqual(provider.requests[0]["max_tokens"], 12000)
        self.assertEqual(len(validator.calls), 1)
        self.assertEqual(outcome["repair_calls"], 0)

    def test_single_repairs_only_after_actual_public_example_failure(self):
        outcome, provider, validator = self.execute("single_tool", [source(SEVEN), source(GOOD)])
        self.assertEqual(outcome["calls"], 2)
        self.assertEqual(outcome["repair_calls"], 1)
        self.assertEqual(len(validator.calls), 2)
        self.assertIn("public example 1", provider.requests[1]["prompt"])
        self.assertEqual(outcome["answer"], source(GOOD))
        self.assertEqual(outcome["status"], "ok")

    def test_single_repairs_best_public_incumbent_not_a_regressed_loser(self):
        outcome, provider, validator = self.execute("single_tool", [source(SEVEN), source(BAD), source(GOOD)])
        self.assertEqual(outcome["status"], "ok")
        self.assertIn(json.dumps(source(SEVEN)), provider.requests[2]["prompt"])
        self.assertNotIn(json.dumps(source(BAD)), provider.requests[2]["prompt"])

    def test_hierarchy_workers_are_isolated_and_only_merge_is_tested(self):
        responses = [{"briefs": ["algorithm", "edge cases"]},
                     {"report": "UNIQUE_WORKER_ONE"}, {"report": "UNIQUE_WORKER_TWO"}, source(GOOD)]
        outcome, provider, validator = self.execute("hierarchy_tool", responses)
        self.assertEqual(outcome["calls"], 4)
        self.assertNotIn("UNIQUE_WORKER_ONE", provider.requests[2]["prompt"])
        self.assertIn("UNIQUE_WORKER_ONE", provider.requests[3]["prompt"])
        self.assertIn("UNIQUE_WORKER_TWO", provider.requests[3]["prompt"])
        self.assertEqual(len(validator.calls), 1)
        self.assertEqual(outcome["repair_calls"], 0)
        self.assertEqual(outcome["coordination_tokens"], 51)

    def test_hierarchy_has_at_most_one_grounded_repair(self):
        responses = [{"briefs": []}, {}, {}, source(BAD), source(SEVEN), source(GOOD)]
        outcome, provider, validator = self.execute("hierarchy_tool", responses)
        self.assertEqual(outcome["calls"], 5)
        self.assertEqual(outcome["repair_calls"], 1)
        self.assertEqual(outcome["status"], "public_tests_failed")
        self.assertEqual(len(validator.calls), 2)

    def test_bazaar_complete_branches_do_not_see_each_other(self):
        first = source(GOOD + "# UNIQUE_BRANCH_ONE_RESPONSE\n")
        outcome, provider, validator = self.execute("bazaar_tool", [first, source(GOOD)])
        self.assertNotIn("UNIQUE_BRANCH_ONE_RESPONSE", provider.requests[1]["prompt"])
        self.assertEqual(outcome["answer"], first)
        event = next(e for e in outcome["trace"] if e["event"] == "deterministic_public_branch_selection")
        self.assertEqual(event["selected_branch"], "branch-1")
        self.assertEqual(outcome["calls"], 2)
        self.assertEqual(len(validator.calls), 2)

    def test_bazaar_ranks_actual_passed_examples_and_repairs_only_winner(self):
        outcome, provider, validator = self.execute("bazaar_tool", [source(BAD), source(SEVEN), source(GOOD)])
        event = next(e for e in outcome["trace"] if e["event"] == "deterministic_public_branch_selection")
        self.assertEqual(event["selected_branch"], "branch-2")
        self.assertIn(json.dumps(source(SEVEN)), provider.requests[2]["prompt"])
        self.assertEqual(outcome["answer"], source(GOOD))
        self.assertEqual(outcome["repair_calls"], 1)

    def test_contract_audits_even_public_passing_source_and_counts_audit(self):
        audit = {"concerns": [{"id": "unverified", "rationale": "Maybe n=10 should be special",
                               "counterexample": {"payload": {"n": 10}, "claimed_expected": {"n": 999}}}]}
        outcome, provider, validator = self.execute("contract_team", [source(GOOD), audit, source(GOOD)])
        self.assertEqual(outcome["calls"], 3)
        self.assertEqual(outcome["audit_calls"], 1)
        self.assertEqual(outcome["audit_output_tokens"], 17)
        self.assertEqual(outcome["coordination_tokens"], 17)
        self.assertEqual(outcome["public_tool_calls"], 2)
        self.assertEqual(outcome["repair_calls"], 0)
        self.assertIn("UNVERIFIED hypotheses", provider.requests[2]["prompt"])
        for call in validator.calls:
            self.assertEqual([case["payload"]["n"] for case in call["examples"]], [7, 8, 9])
        event = next(e for e in outcome["trace"] if e["event"] == "independent_audit_hypotheses")
        self.assertFalse(event["counterexamples_executed"])
        self.assertFalse(event["claimed_expected_values_are_ground_truth"])

    def test_contract_rejects_public_regression_without_extra_repairs_to_a_loser(self):
        outcome, provider, validator = self.execute("contract_team", [source(GOOD), {"concerns": []}, source(BAD)])
        self.assertEqual(outcome["calls"], 3)
        self.assertEqual(outcome["answer"], source(GOOD))
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["repair_calls"], 0)

    def test_contract_repairs_failed_revision_using_real_public_feedback(self):
        outcome, provider, validator = self.execute("contract_team", [source(BAD), {"concerns": []},
                                                                       source(SEVEN), source(GOOD)])
        self.assertEqual(outcome["calls"], 4)
        self.assertEqual(outcome["repair_calls"], 1)
        self.assertEqual(outcome["answer"], source(GOOD))
        self.assertIn("ACTUAL public-example", provider.requests[3]["prompt"])

    def test_all_llm_stage_allowances_share_one_common_total(self):
        configurations = {
            "single_tool": [source(GOOD)],
            "hierarchy_tool": [{"briefs": []}, {}, {}, source(GOOD)],
            "bazaar_tool": [source(GOOD), source(GOOD)],
            "contract_team": [source(GOOD), {"concerns": []}, source(GOOD)],
            "adaptive_tools": [source(GOOD), {"concerns": []}, source(GOOD)],
        }
        for name, responses in configurations.items():
            with self.subTest(name=name):
                provider = StubProvider(responses, use_full_allowance=True)
                outcome, _, _ = self.execute(name, responses, provider=provider, complexity_threshold=0)
                self.assertLessEqual(outcome["calls"], 5)
                self.assertLessEqual(outcome["output_tokens"], 12000)
                self.assertLessEqual(sum(r["max_tokens"] for r in provider.requests), 12000)
                self.assertEqual(outcome["status"], "ok")

    def test_adaptive_route_uses_only_frozen_public_features_not_family_or_hidden(self):
        a = problem("If a previous item exists, only apply after it.", {"switch": True})
        b = dict(a, family="arbitrary_changed_family", private={"hidden_success": 1})
        threshold = public_route_features(a["public"])["complexity_score"]
        outcomes = []
        for task in (a, b):
            outcome, provider, _ = self.execute("adaptive_tools", [source(GOOD), {"concerns": []}, source(GOOD)],
                                                 task=task, complexity_threshold=threshold)
            outcomes.append(outcome)
        self.assertEqual(outcomes[0]["effective_architecture"], "contract_team")
        self.assertEqual(outcomes[1]["effective_architecture"], "contract_team")
        self.assertEqual(outcomes[0]["trace"][0], outcomes[1]["trace"][0])
        self.assertFalse(outcomes[0]["trace"][0]["features"]["reads_family"])
        single, _, _ = self.execute("adaptive_tools", [source(GOOD)], task=a, complexity_threshold=threshold + 1)
        self.assertEqual(single["effective_architecture"], "single_tool")
        self.assertEqual(single["calls"], 1)

    def test_public_feature_formula_is_explicit_and_model_independent(self):
        features = public_route_features({"spec": "If previous then only after current.",
                                          "rules": {"x": [1, 2], "nested": {"flag": False}}})
        self.assertEqual(features["primitive_rule_values"], 3)
        self.assertEqual(features["conditional_markers"], 2)
        self.assertEqual(features["dependency_markers"], 3)
        self.assertEqual(features["complexity_score"], 11)

    def test_private_never_reaches_any_public_validator_or_model_prompt(self):
        for name, responses in [("single_tool", [source(GOOD)]),
                                ("hierarchy_tool", [{}, {}, {}, source(GOOD)]),
                                ("bazaar_tool", [source(GOOD), source(GOOD)]),
                                ("contract_team", [source(GOOD), {}, source(GOOD)])]:
            with self.subTest(name=name):
                outcome, provider, validator = self.execute(name, responses)
                json.dumps(outcome)
                self.assertFalse(outcome["hidden_evaluator_called"])
                self.assertNotIn("PrivateTrap", json.dumps(provider.requests))

    def test_validator_failure_is_not_treated_as_a_passing_test(self):
        def broken(task, answer):
            raise RuntimeError("secret-text-not-for-reflection")
        outcome, _, _ = self.execute("single_tool", [source(GOOD)], validator=broken, max_calls=1)
        self.assertEqual(outcome["status"], "public_tests_failed")
        self.assertFalse(outcome["public_feedback"]["success"])
        self.assertNotIn("secret-text", json.dumps(outcome))

    def test_incomplete_mandatory_audit_protocol_does_not_claim_completion(self):
        outcome, provider, validator = self.execute("contract_team", [source(GOOD), {"concerns": []}], max_calls=2)
        self.assertEqual(outcome["calls"], 2)
        self.assertEqual(outcome["status"], "budget_exhausted")
        self.assertEqual(outcome["answer"], source(GOOD))

    def test_provider_error_keeps_attempt_accounting_without_echoing_secrets(self):
        provider = StubProvider([source(GOOD)], fail_at=1)
        outcome, _, _ = self.execute("contract_team", [], provider=provider)
        self.assertEqual(outcome["calls"], 2)
        self.assertEqual(outcome["output_tokens"], 17)
        self.assertEqual(outcome["status"], "provider_error")
        self.assertFalse(outcome["usage_complete"])
        self.assertNotIn("must-not-copy-credential-token", json.dumps(outcome))


if __name__ == "__main__":
    unittest.main()
