"""Public-only controls: protocol, cost accounting and genuine tool feedback."""
from __future__ import annotations

import ast
import json
import unittest

from orgbench.advanced_organizations import (DESCRIPTIONS, public_risk_features,
                                             run_advanced_organization)
from orgbench.tool_organizations import run_tool_organization


GOOD = 'def solve(payload):\n    return {"n": payload["n"]}\n'
SEVEN = 'def solve(payload):\n    return {"n": 7}\n'
BAD = 'def solve(payload):\n    return {"n": 99}\n'
HIGH_SPEC = "If n is supplied, it must be returned. " * 6


class PrivateTrap:
    def __repr__(self):
        raise AssertionError("private values were inspected")

    def __deepcopy__(self, memo):
        raise AssertionError("private values were copied")


def problem(spec="Return n unchanged."):
    return {"id": "toy-advanced", "family": "family-must-not-route",
            "prompt": "Implement solve(payload) returning {'n': payload['n']}. " + spec,
            "schema": {"source": "complete Python source"},
            "public": {"spec": spec, "examples": [
                {"payload": {"n": n}, "expected": {"n": n}} for n in (7, 8, 9)]},
            "private": PrivateTrap()}


def source(code):
    return {"source": code}


class ToyPublicValidator:
    """Evaluate the fixture's tiny return-expression subset without exec/eval."""
    def __init__(self):
        self.calls = []

    def __call__(self, task, answer):
        if "private" in task:
            raise AssertionError("private task crossed the tool boundary")
        self.calls.append(answer)
        total = len(task["public"]["examples"])
        try:
            tree = ast.parse(answer["source"])
            function = tree.body[0]
            if not isinstance(function, ast.FunctionDef) or function.name != "solve":
                raise ValueError("missing solve")
            statement = function.body[0]
            if not isinstance(statement, ast.Return):
                raise ValueError("unsupported return")

            def expression(node, payload):
                if isinstance(node, ast.Constant):
                    return node.value
                if isinstance(node, ast.Dict):
                    return {expression(key, payload): expression(value, payload)
                            for key, value in zip(node.keys, node.values)}
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "payload":
                    return payload[expression(node.slice, payload)]
                raise ValueError("unsupported expression")

            passed, violations = 0, []
            for index, case in enumerate(task["public"]["examples"]):
                got = expression(statement.value, case["payload"])
                if got == case["expected"]:
                    passed += 1
                else:
                    violations.append(f"public example {index}: expected {case['expected']}, got {got}")
            return {"success": passed == total, "score": passed / total,
                    "valid_syntax": True, "public_passed": passed,
                    "public_total": total, "violations": violations}
        except (KeyError, SyntaxError, ValueError, TypeError, AttributeError, IndexError):
            return {"success": False, "score": 0.0, "valid_syntax": False,
                    "public_passed": 0, "public_total": total,
                    "violations": ["invalid supported source"]}


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
            raise RuntimeError("credential-value-must-not-leak")
        response = self.responses[min(index, len(self.responses) - 1)]
        return {"text": response if isinstance(response, str) else json.dumps(response),
                "input_tokens": 101, "cache_read_input_tokens": 21,
                "output_tokens": max_tokens if self.use_full_allowance else 17,
                "model": "test-only", "latency_s": 0.01}


class AdvancedOrganizationTests(unittest.TestCase):
    def execute(self, name, responses, **kwargs):
        provider = kwargs.pop("provider", StubProvider(responses))
        validator = kwargs.pop("validator", ToyPublicValidator())
        task = kwargs.pop("task", problem())
        result = run_advanced_organization(name, task, provider,
                                            public_validator=validator, **kwargs)
        return result, provider, validator

    def test_plain_is_one_shot_on_both_pass_and_fail(self):
        for code, status in ((GOOD, "ok"), (BAD, "public_tests_failed")):
            with self.subTest(status=status):
                result, provider, validator = self.execute("plain_single", [source(code), source(GOOD)])
                self.assertEqual((result["calls"], result["repair_calls"]), (1, 0))
                self.assertEqual(result["status"], status)
                self.assertEqual(provider.requests[0]["max_tokens"], 12000)
                self.assertEqual(len(validator.calls), 1)

    def test_self_review_three_calls_even_after_public_pass(self):
        initial = source(GOOD + "# INITIAL_SOURCE_SENTINEL\n")
        review = {"findings": [{"suspected_issue": "REVIEW_SENTINEL", "rationale": "check"}]}
        result, provider, validator = self.execute("single_self_review", [initial, review, source(GOOD)])
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["calls"], result["self_review_calls"], result["audit_calls"]), (3, 1, 0))
        self.assertEqual((result["coordination_tokens"], result["self_review_output_tokens"]), (17, 17))
        self.assertEqual(len(validator.calls), 2)
        for request in provider.requests[1:]:
            self.assertIn("INITIAL_SOURCE_SENTINEL", request["prompt"])
            self.assertIn("public_test_tool", request["prompt"])
            self.assertIn("Return n unchanged", request["prompt"])
        self.assertIn("REVIEW_SENTINEL", provider.requests[2]["prompt"])
        event = next(e for e in result["trace"] if e["event"] == "full_history_self_review")
        self.assertFalse(event["independent_auditor"])

    def test_self_review_matches_contract_mandatory_stage_allowances(self):
        responses = [source(GOOD), {"findings": []}, source(GOOD)]
        provider = StubProvider(responses, use_full_allowance=True)
        result, _, _ = self.execute("single_self_review", responses, provider=provider)
        contract_provider = StubProvider(responses, use_full_allowance=True)
        contract = run_tool_organization("contract_team", problem(), contract_provider,
                                        public_validator=ToyPublicValidator())
        self.assertEqual([r["max_tokens"] for r in provider.requests], [7200, 1200, 3600])
        self.assertEqual([r["max_tokens"] for r in provider.requests],
                         [r["max_tokens"] for r in contract_provider.requests])
        self.assertEqual(result["output_tokens"], contract["output_tokens"])
        self.assertEqual(result["output_tokens"], 12000)
        self.assertEqual(contract["audit_calls"], 1)
        self.assertNotIn("public_test_tool", contract_provider.requests[1]["prompt"])

    def test_self_review_history_is_complete_without_recursive_transport_copies(self):
        task = problem()
        task["prompt"] += " UNIQUE_TASK_ONLY_ONCE"
        result, provider, _ = self.execute("single_self_review", [source(BAD), {}, source(BAD)], task=task)
        self.assertEqual(result["calls"], 5)
        for request in provider.requests:
            self.assertEqual(request["prompt"].count("UNIQUE_TASK_ONLY_ONCE"), 1)
        self.assertIn("self-repair-1", provider.requests[-1]["prompt"])

    def test_self_review_does_not_replace_a_passing_incumbent_with_bad_revision(self):
        result, _, _ = self.execute("single_self_review", [source(GOOD), {}, source(BAD)])
        self.assertEqual(result["answer"], source(GOOD))
        self.assertEqual((result["calls"], result["repair_calls"]), (3, 0))
        self.assertEqual(result["status"], "ok")

    def test_self_review_repairs_retain_same_solver_full_history(self):
        result, provider, _ = self.execute("single_self_review", [source(SEVEN),
            {"findings": ["SELF_REVIEW_MEMORY"]}, source(BAD), source(GOOD)], max_input_tokens=100000)
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["calls"], result["repair_calls"]), (4, 1))
        self.assertIn("SELF_REVIEW_MEMORY", provider.requests[3]["prompt"])
        self.assertIn("public example 1", provider.requests[3]["prompt"])
        self.assertNotIn("Independent audit hypotheses", provider.requests[3]["prompt"])

    def test_best_of_three_isolates_branches_and_uses_low_branch_id_tie(self):
        first = source(GOOD + "# UNIQUE_BRANCH_1\n")
        second = source(GOOD + "# UNIQUE_BRANCH_2\n")
        result, provider, validator = self.execute("best_of_three", [first, second, source(GOOD)])
        self.assertEqual(result["answer"], first)
        self.assertEqual((result["calls"], result["public_tool_calls"]), (3, 3))
        self.assertEqual(len(validator.calls), 3)
        self.assertEqual([r["max_tokens"] for r in provider.requests], [3000, 3000, 3000])
        self.assertNotIn("UNIQUE_BRANCH_1", provider.requests[1]["prompt"])
        self.assertNotIn("UNIQUE_BRANCH_1", provider.requests[2]["prompt"])
        self.assertNotIn("UNIQUE_BRANCH_2", provider.requests[2]["prompt"])
        event = next(e for e in result["trace"] if e["event"] == "best_of_three_public_selection")
        self.assertFalse(event["majority_vote"])
        self.assertEqual(event["selected_branch"], "branch-1")

    def test_best_of_three_ranks_actual_public_results_before_optional_repair(self):
        result, provider, _ = self.execute("best_of_three", [source(BAD), source(SEVEN), {}, source(GOOD)])
        self.assertEqual((result["calls"], result["repair_calls"]), (4, 1))
        self.assertEqual(result["status"], "ok")
        event = next(e for e in result["trace"] if e["event"] == "best_of_three_public_selection")
        self.assertEqual(event["selected_branch"], "branch-2")
        self.assertIn(json.dumps(source(SEVEN)), provider.requests[3]["prompt"])

    def test_gate_low_risk_pass_stops_at_one_call(self):
        result, _, _ = self.execute("evidence_gated", [source(GOOD)])
        self.assertEqual((result["status"], result["calls"], result["audit_calls"]), ("ok", 1, 0))
        event = next(e for e in result["trace"] if e["event"] == "evidence_gate_route")
        self.assertEqual(event["reason"], "public_pass_low_static_risk")

    def test_gate_high_risk_public_pass_audits_existing_source(self):
        hypotheses = {"concerns": [{"counterexample": {"payload": {"n": 123}, "claimed_expected": {"n": 0}}}]}
        result, provider, validator = self.execute("evidence_gated", [source(GOOD), hypotheses, source(GOOD)],
                                                  task=problem(HIGH_SPEC))
        self.assertEqual((result["status"], result["calls"], result["audit_calls"]), ("ok", 3, 1))
        self.assertEqual(result["audit_output_tokens"], 17)
        self.assertEqual(len(validator.calls), 2)
        self.assertIn("UNVERIFIED", provider.requests[1]["prompt"])
        self.assertIn("UNVERIFIED", provider.requests[2]["prompt"])
        self.assertFalse(result["audit_expected_values_grounded"])
        self.assertEqual(result["trace"][0]["event"], "evidence_gate_policy_frozen")
        self.assertFalse(result["trace"][0]["learned_from_hidden_scores"])

    def test_gate_uses_real_failure_repair_before_auditing(self):
        result, provider, _ = self.execute("evidence_gated", [source(BAD), source(GOOD)], task=problem(HIGH_SPEC))
        self.assertEqual((result["calls"], result["audit_calls"], result["repair_calls"]), (2, 0, 1))
        self.assertEqual(provider.requests[1]["max_tokens"], 2400)
        event = next(e for e in result["trace"] if e["event"] == "evidence_gate_route")
        self.assertEqual(event["reason"], "public_failure_repaired")
        self.assertEqual(result["status"], "ok")

    def test_gate_persistent_failure_audits_without_a_duplicate_initial_solver(self):
        result, provider, _ = self.execute("evidence_gated", [source(BAD), source(SEVEN), {}, source(GOOD)])
        self.assertEqual((result["calls"], result["audit_calls"], result["repair_calls"]), (4, 1, 1))
        self.assertEqual(result["status"], "ok")
        roles = [r["system"] for r in provider.requests]
        self.assertEqual(sum("initial solver" in role for role in roles), 1)
        event = next(e for e in result["trace"] if e["event"] == "evidence_gate_route")
        self.assertEqual(event["reason"], "public_failure_persists")

    def test_gate_keeps_public_passing_initial_when_audit_revision_regresses(self):
        result, _, _ = self.execute("evidence_gated", [source(GOOD), {}, source(BAD)], task=problem(HIGH_SPEC))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["answer"], source(GOOD))
        self.assertEqual(result["repair_calls"], 0)

    def test_gate_features_are_public_fixed_and_structural(self):
        low = public_risk_features(problem()["public"], source(GOOD))
        high = public_risk_features(problem(HIGH_SPEC)["public"], source(GOOD))
        self.assertFalse(low["static_undercoverage_risk"])
        self.assertTrue(high["static_undercoverage_risk"])
        self.assertFalse(high["reads_family"])
        self.assertFalse(high["reads_hidden_score"])
        long_code = "def solve(payload):\n" + "    if False:\n        pass\n" * 12 + "    return payload\n"
        ample = public_risk_features(problem(HIGH_SPEC)["public"], source(long_code))
        self.assertFalse(ample["static_undercoverage_risk"])

    def test_every_architecture_respects_private_canary_and_shared_budgets(self):
        for name in DESCRIPTIONS:
            with self.subTest(name=name):
                provider = StubProvider([source(GOOD), {}, source(GOOD)], use_full_allowance=True)
                result, _, validator = self.execute(name, [], provider=provider)
                self.assertLessEqual(result["calls"], 5)
                self.assertLessEqual(result["output_tokens"], 12000)
                self.assertEqual(result["input_tokens"], 101 * result["calls"])
                self.assertEqual(result["cache_read_input_tokens"], 21 * result["calls"])
                self.assertEqual(result["public_tool_calls"], len(validator.calls))
                self.assertFalse(result["hidden_evaluator_called"])
                json.dumps(result)

    def test_validator_exception_is_infrastructure_failure_and_stops_spend(self):
        def broken(task, answer):
            raise RuntimeError("sensitive-executor-details")
        for name in DESCRIPTIONS:
            with self.subTest(name=name):
                result, _, _ = self.execute(name, [source(GOOD)], validator=broken)
                self.assertEqual((result["status"], result["calls"]), ("evaluator_error", 1))
                self.assertEqual(result["error"], "public_test_infrastructure_error")
                self.assertNotIn("sensitive-executor-details", json.dumps(result))

    def test_executor_infrastructure_flag_cannot_be_a_passing_model_result(self):
        def broken(task, answer):
            return {"success": True, "valid_syntax": True, "public_passed": 3,
                    "public_total": 3, "violations": [], "executor_infrastructure_error": True}
        result, _, _ = self.execute("single_self_review", [source(GOOD)], validator=broken)
        self.assertEqual((result["status"], result["calls"]), ("evaluator_error", 1))

    def test_provider_error_preserves_metrics_without_exception_secrets(self):
        provider = StubProvider([source(GOOD)], fail_at=1)
        result, _, _ = self.execute("single_self_review", [], provider=provider)
        self.assertEqual((result["status"], result["calls"]), ("provider_error", 2))
        self.assertEqual(result["input_tokens"], 101)
        self.assertFalse(result["usage_complete"])
        self.assertNotIn("credential-value-must-not-leak", json.dumps(result))
        self.assertEqual(result["answer"], source(GOOD))

    def test_incomplete_mandatory_protocol_is_not_declared_success(self):
        result, _, _ = self.execute("single_self_review", [source(GOOD), {}], max_calls=2)
        self.assertEqual((result["status"], result["calls"]), ("budget_exhausted", 2))
        self.assertEqual(result["answer"], source(GOOD))

    def test_preflight_input_budget_blocks_model_before_any_call(self):
        for name in DESCRIPTIONS:
            with self.subTest(name=name):
                result, provider, _ = self.execute(name, [source(GOOD)], max_input_tokens=1)
                self.assertEqual((result["status"], result["calls"]), ("input_budget_exhausted", 0))
                self.assertEqual(provider.requests, [])

    def test_bad_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            self.execute("not-a-control", [source(GOOD)])
        for key in ("max_calls", "max_output_tokens", "max_input_tokens"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.execute("plain_single", [source(GOOD)], **{key: 0})


if __name__ == "__main__":
    unittest.main()
