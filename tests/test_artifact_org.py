from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from orgbench.artifact_org import (prepare_public_artifacts, run_artifact_contracts, run_contract_adaptive,
                                       run_artifact_single)
from orgbench.tasks import validate_public


class ForbiddenPrivate:
    def __deepcopy__(self, memo):
        raise AssertionError("Private data was touched")

    def __getitem__(self, key):
        raise AssertionError("Private data was read")


class StubProvider:
    def __init__(self, answers, *, use_full_budget=False):
        self.answers = list(answers)
        self.requests = []
        self.use_full_budget = use_full_budget

    def complete(self, system, prompt, max_tokens=None):
        index = len(self.requests)
        self.requests.append({"system": system, "prompt": prompt, "max_tokens": max_tokens})
        answer = self.answers[min(index, len(self.answers) - 1)]
        return {"text": answer if isinstance(answer, str) else json.dumps(answer),
                "input_tokens": 100, "output_tokens": max_tokens if self.use_full_budget else 20,
                "cache_read_input_tokens": 25, "latency_s": 0.01}


def task(family, public, schema):
    rules = "Apply the public rules for " + family + ". Keep exact types and provenance."
    return {"id": "fixture_" + family, "family": family,
            "public": public, "schema": schema,
            "prompt": rules + "\n\nINPUT:\n" + json.dumps(public)
                      + "\n\nReturn only a JSON object.",
            "private": ForbiddenPrivate()}


def evidence_fixture():
    keys = ["A.status", "A.quota", "B.status", "B.quota", "C.status", "C.quota"]
    records = [{"id": "R" + str(i + 1), "key": key, "value": i + 10,
                "publisher": "registry", "issued": 10} for i, key in enumerate(keys)]
    public = {"requested": keys, "records": records,
              "revocations": [{"target": "R1", "at": 30}],
              "authority": {"registry": 3, "memo": 1}, "cutoff": 20}
    schema = {"facts": {key: {"value": "integer", "source": "R id"} for key in keys}}
    answers = [{"facts": {keys[i]: {"value": i + 10, "source": "R" + str(i + 1)}
                           for i in indexes}} for indexes in ([0, 1], [2, 3], [4, 5])]
    return task("evidence", public, schema), answers


def planning_fixture():
    public = {"budget": 7, "hours_cap": 7, "projects": [
        {"id": "P1", "cost": 2, "hours": 2, "value": 2, "requires": []},
        {"id": "P2", "cost": 2, "hours": 2, "value": 2, "requires": []},
        {"id": "P3", "cost": 4, "hours": 4, "value": 10, "requires": []},
        {"id": "P4", "cost": 3, "hours": 3, "value": 9, "requires": ["P1"]},
    ], "exclusive_groups": [], "synergies": [{"pair": ["P1", "P4"], "bonus": 3}]}
    return task("planning", public, {"selected": ["P id"]})


def sequential_fixture():
    public = {"initial_balances": {"A": 100, "B": 80, "C": 50}, "initial_frozen": [], "events": [
        {"id": "E1", "op": "credit", "account": "A", "amount": 10},
        {"id": "E2", "op": "transfer", "from": "A", "to": "B", "amount": 30},
        {"id": "E3", "op": "freeze", "account": "B"},
        {"id": "E1", "op": "credit", "account": "A", "amount": 999},
        {"id": "E4", "op": "debit", "account": "B", "amount": 5},
        {"id": "E5", "op": "credit", "account": "B", "amount": 20},
        {"id": "E6", "op": "unfreeze", "account": "B"},
        {"id": "E7", "op": "transfer", "from": "B", "to": "C", "amount": 15},
        {"id": "E8", "op": "bonus_if", "account": "A", "amount": 7, "if_account": "C", "threshold": 60},
        {"id": "C1", "op": "cancel", "target": "E2"},
    ]}
    states = [{"balances": {"A": 110, "B": 80, "C": 50}, "frozen": ["B"], "accepted": 2},
              {"balances": {"A": 110, "B": 100, "C": 50}, "frozen": ["B"], "accepted": 3},
              {"balances": {"A": 117, "B": 85, "C": 65}, "frozen": [], "accepted": 6}]
    return task("sequential", public, {"balances": {"A": "int", "B": "int", "C": "int"},
                                       "frozen": ["id"], "accepted": "int"}), states


class ArtifactOrganizationTests(unittest.TestCase):
    def test_adaptive_contract_route_uses_public_family_and_preserves_shared_control(self):
        problem, answers = evidence_fixture()
        outcome = run_contract_adaptive(problem, StubProvider(answers))
        self.assertEqual(outcome["architecture"], "contract_adaptive")
        self.assertEqual(outcome["effective_architecture"], "artifact_contracts")
        self.assertFalse(outcome["trace"][0]["learned"])
        selected = {"selected": ["P1", "P4"]}
        outcome = run_contract_adaptive(planning_fixture(), StubProvider([selected]))
        self.assertEqual(outcome["effective_architecture"], "artifact_single")
        self.assertEqual(outcome["answer"], selected)

    def test_evidence_contracts_are_disjoint_complete_and_preserve_provenance(self):
        problem, answers = evidence_fixture()
        provider = StubProvider(answers)
        outcome = run_artifact_contracts(problem, provider)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["calls"], 3)
        self.assertEqual(set(outcome["answer"]["facts"]), set(problem["public"]["requested"]))
        self.assertEqual(outcome["answer"]["facts"]["C.quota"], {"value": 15, "source": "R6"})
        self.assertNotIn("B.status", provider.requests[0]["prompt"])
        self.assertNotIn("R6", provider.requests[1]["prompt"])
        self.assertIn("Keep exact types and provenance", provider.requests[2]["prompt"])
        self.assertEqual(outcome["trace"][-1]["llm_manager_calls"], 0)

    def test_evidence_local_repair_only_sees_its_assigned_shard(self):
        problem, answers = evidence_fixture()
        invalid = copy.deepcopy(answers[0])
        invalid["facts"]["A.status"]["source"] = "R999"
        provider = StubProvider([invalid, answers[1], answers[2], answers[0]])
        outcome = run_artifact_contracts(problem, provider)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["calls"], 4)
        self.assertIn("unknown source", provider.requests[3]["prompt"])
        self.assertNotIn("C.quota", provider.requests[3]["prompt"])
        self.assertEqual(outcome["answer"]["facts"]["A.status"]["source"], "R1")

    def test_preprocessing_does_not_execute_the_ledger(self):
        problem, states = sequential_fixture()
        with patch("orgbench.tasks._sequential_answer", side_effect=AssertionError("oracle used")):
            prepared = prepare_public_artifacts(problem)
        public = prepared["task"]["public"]
        self.assertEqual(public["initial_balances"], {"A": 100, "B": 80, "C": 50})
        self.assertEqual([event["id"] for event in public["events"]],
                         ["E1", "E3", "E4", "E5", "E6", "E7", "E8"])
        self.assertEqual(public["events"][0]["amount"], 10)
        self.assertFalse(prepared["normalization"]["computed_ledger_state"])

    def test_sequential_state_handoffs_preserve_all_fields_and_cumulative_accepted(self):
        problem, states = sequential_fixture()
        provider = StubProvider(states)
        outcome = run_artifact_contracts(problem, provider)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["answer"], states[-1])
        self.assertEqual(outcome["calls"], 3)
        self.assertIn('"initial_balances":{"A":110,"B":80,"C":50}', provider.requests[1]["prompt"])
        self.assertIn("incoming cumulative accepted count is 2", provider.requests[1]["prompt"])
        self.assertIn("incoming cumulative accepted count is 3", provider.requests[2]["prompt"])
        self.assertNotIn('"id":"E1"', provider.requests[1]["prompt"])
        gates = [event for event in outcome["trace"] if event["event"] == "artifact_feasibility_gate"]
        self.assertTrue(all(gate["passed"] for gate in gates))

    def test_sequential_invalid_state_cannot_feed_the_next_segment(self):
        problem, states = sequential_fixture()
        invalid = dict(states[0], accepted=99)
        provider = StubProvider([invalid])
        outcome = run_artifact_contracts(problem, provider, max_calls=3)
        self.assertEqual(outcome["status"], "contract_failure")
        self.assertIsNone(outcome["answer"])
        self.assertEqual(outcome["calls"], 1)

    def test_planning_partitions_cover_every_anchor_assignment(self):
        prepared = prepare_public_artifacts(planning_fixture())
        assignments = {(tuple(c["must_include"]), tuple(c["must_exclude"])) for c in prepared["contracts"]}
        self.assertEqual(len(assignments), 4)
        for contract in prepared["contracts"]:
            self.assertEqual(set(contract["must_include"]) | set(contract["must_exclude"]), {"P1", "P2"})
            self.assertFalse(set(contract["must_include"]) & set(contract["must_exclude"]))

    def test_planning_merge_uses_public_candidate_value_not_a_hidden_optimum(self):
        problem = planning_fixture()
        # Submitted best is utility 14, although P1,P2,P4 would have utility 16.
        # The mechanism must not invent that missing globally optimal candidate.
        provider = StubProvider([{"selected": ["P3"]}, {"selected": ["P2", "P3"]},
                                 {"selected": ["P1", "P4"]}, {"selected": ["P1", "P2"]}])
        with patch("orgbench.tasks._planning_optimum", side_effect=AssertionError("oracle used")):
            outcome = run_artifact_contracts(problem, provider)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["answer"], {"selected": ["P1", "P4"]})
        merge = outcome["trace"][-1]
        self.assertEqual(merge["selected_public_utility"], 14)
        self.assertFalse(merge["exhaustive_optimality_claim"])

    def test_planning_gate_enforces_subspace_and_original_feasibility(self):
        problem = planning_fixture()
        provider = StubProvider([{"selected": ["P1", "P4"]}, {"selected": ["P2", "P3"]},
                                 {"selected": ["P1", "P4"]}, {"selected": ["P1", "P2"]},
                                 {"selected": ["P3"]}])
        outcome = run_artifact_contracts(problem, provider)
        gates = [event for event in outcome["trace"] if event["event"] == "artifact_feasibility_gate"]
        self.assertIn("candidate selects a fixed excluded anchor", gates[0]["violations"])
        self.assertEqual(outcome["calls"], 5)
        self.assertEqual(outcome["answer"], {"selected": ["P1", "P4"]})

    def test_single_control_gets_normalized_input_and_five_public_feedback_rounds(self):
        problem, states = sequential_fixture()
        provider = StubProvider([states[-1]])
        outcome = run_artifact_single(problem, provider)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["calls"], 5)
        self.assertEqual(outcome["answer"], states[-1])
        self.assertIn('"id":"E1"', provider.requests[0]["prompt"])
        self.assertNotIn('"id":"E2"', provider.requests[0]["prompt"])
        self.assertNotIn('"amount":999', provider.requests[0]["prompt"])
        self.assertIn("PUBLIC feedback", provider.requests[1]["prompt"])

    def test_single_receives_same_actual_grouped_evidence_not_only_shard_names(self):
        problem, answers = evidence_fixture()
        full_answer = {"facts": {key: fact for answer in answers for key, fact in answer["facts"].items()}}
        provider = StubProvider([full_answer])
        outcome = run_artifact_single(problem, provider, max_calls=1)
        self.assertEqual(outcome["status"], "ok")
        prompt = provider.requests[0]["prompt"]
        grouped = json.loads(prompt.split("\n\nINPUT:\n", 1)[1].split("\nReturn one complete answer", 1)[0])
        original = problem["public"]
        self.assertEqual([r for shard in grouped["shards"] for r in shard["records"]], original["records"])
        self.assertEqual(grouped["authority"], original["authority"])
        self.assertEqual(sum(len(shard["requested"]) for shard in grouped["shards"]), len(original["requested"]))

    def test_optional_single_refinement_keeps_complete_feasible_incumbent_at_preflight_stop(self):
        provider = StubProvider([{"selected": ["P1", "P4"]}])
        with patch("orgbench.architectures._estimate_input", return_value=100):
            outcome = run_artifact_single(planning_fixture(), provider, max_input_tokens=150)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["calls"], 1)
        self.assertEqual(outcome["answer"], {"selected": ["P1", "P4"]})

    def test_single_control_retains_best_publicly_feasible_planning_candidate(self):
        problem = planning_fixture()
        provider = StubProvider([{"selected": ["P1", "P4"]}, {"selected": ["P1", "P2", "P4"]},
                                 {"selected": []}, {"selected": ["P2", "P3"]},
                                 {"selected": ["P3", "P4"]}])
        outcome = run_artifact_single(problem, provider)
        self.assertEqual(outcome["answer"], {"selected": ["P1", "P2", "P4"]})
        self.assertIn("Incumbent PUBLIC utility: 16", provider.requests[2]["prompt"])
        self.assertEqual(outcome["status"], "ok")

    def test_common_budget_and_no_partial_artifact_as_final_answer(self):
        problem, answers = evidence_fixture()
        for runner in (run_artifact_contracts, run_artifact_single):
            provider = StubProvider(answers, use_full_budget=True)
            outcome = runner(problem, provider, max_output_tokens=3600)
            self.assertLessEqual(outcome["output_tokens"], 3600)
            self.assertLessEqual(outcome["calls"], 5)
            self.assertLessEqual(sum(r["max_tokens"] for r in provider.requests), 3600)
        provider = StubProvider(answers)
        outcome = run_artifact_contracts(problem, provider, max_calls=2)
        self.assertEqual(outcome["calls"], 2)
        self.assertEqual(outcome["status"], "budget_exhausted")
        self.assertIsNone(outcome["answer"])

    def test_private_data_never_reaches_prompt_trace_or_validator(self):
        problem, answers = evidence_fixture()
        seen = []

        def validator(public_task, answer):
            self.assertNotIn("private", public_task)
            seen.append(public_task)
            return validate_public(public_task, answer)

        provider = StubProvider(answers)
        outcome = run_artifact_contracts(problem, provider, public_validator=validator)
        self.assertTrue(seen)
        self.assertFalse(outcome["uses_hidden_answers"])
        self.assertNotIn("ForbiddenPrivate", json.dumps(outcome))


if __name__ == "__main__":
    unittest.main()
