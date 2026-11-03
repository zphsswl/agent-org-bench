import copy
import itertools
import unittest

from orgbench.tasks import (evaluate, generate_suite, validate_public, _evidence_answer,
                            _planning_feasibility, _planning_value, _sequential_answer)


class TaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = generate_suite(per_family=2)

    def task(self, family):
        return copy.deepcopy(next(t for t in self.tasks if t["family"] == family))

    def test_deterministic_and_disjoint_splits(self):
        self.assertEqual(self.tasks, generate_suite(per_family=2))
        holdout = generate_suite(split="holdout", per_family=2)
        self.assertTrue(set(t["id"] for t in holdout).isdisjoint(t["id"] for t in self.tasks))
        self.assertTrue(set(t["prompt"] for t in holdout).isdisjoint(t["prompt"] for t in self.tasks))

    def test_oracle_answers_all_valid(self):
        for task in self.tasks:
            with self.subTest(task=task["id"]):
                self.assertEqual([], validate_public(task, task["private"]["answer"]))
                self.assertTrue(evaluate(task, task["private"]["answer"])["success"])

    def test_public_validator_works_with_private_removed(self):
        for task in self.tasks:
            answer = task["private"]["answer"]
            public_task = {k: v for k, v in task.items() if k != "private"}
            self.assertEqual([], validate_public(public_task, answer))

    def test_evidence_authority_cutoff_and_numeric_tie(self):
        task = self.task("evidence")
        public = {"cutoff": 20, "authority": {"high": 3, "low": 1},
                  "requested": ["x"], "revocations": [{"target": "R12", "at": 19},
                                                            {"target": "R10", "at": 21}],
                  "records": [
                      {"id": "R2", "key": "x", "value": 2, "publisher": "high", "issued": 5},
                      {"id": "R10", "key": "x", "value": 10, "publisher": "high", "issued": 5},
                      {"id": "R11", "key": "x", "value": 11, "publisher": "low", "issued": 20},
                      {"id": "R12", "key": "x", "value": 12, "publisher": "high", "issued": 19},
                      {"id": "R13", "key": "x", "value": 13, "publisher": "high", "issued": 21}]}
        expected = {"facts": {"x": {"value": 10, "source": "R10"}}}
        self.assertEqual(expected, _evidence_answer(public))
        task.update(public=public, private={"answer": expected})
        wrong = {"facts": {"x": {"value": 11, "source": "R11"}}}
        self.assertEqual([], validate_public(task, wrong))
        self.assertFalse(evaluate(task, wrong)["success"])
        task["public"]["records"].reverse()
        self.assertEqual(expected, _evidence_answer(task["public"]))

    def test_evidence_source_matters_even_with_right_value(self):
        task = self.task("evidence")
        answer = copy.deepcopy(task["private"]["answer"])
        key = next(iter(answer["facts"]))
        answer["facts"][key]["source"] = "R999"
        result = evaluate(task, answer)
        self.assertFalse(result["success"])
        self.assertAlmostEqual(result["score"], 5 / 6)

    def test_planning_feasible_but_suboptimal_is_not_success(self):
        task = self.task("planning")
        self.assertEqual([], validate_public(task, {"selected": []}))
        result = evaluate(task, {"selected": []})
        self.assertFalse(result["success"])
        self.assertEqual(0.0, result["score"])
        self.assertIn("suboptimal", result["violations"][0])

    def test_planning_any_optimum_order_and_ties_accepted(self):
        task = self.task("planning")
        task["public"] = {"budget": 1, "hours_cap": 1, "exclusive_groups": [], "synergies": [],
                          "projects": [{"id": p, "cost": 1, "hours": 1, "value": 3, "requires": []}
                                       for p in ("P1", "P2")]}
        task["private"] = {"answer": {"selected": ["P1"]}, "optimal_value": 3}
        self.assertTrue(evaluate(task, {"selected": ["P2"]})["success"])
        base = self.task("planning")
        reversed_answer = {"selected": list(reversed(base["private"]["answer"]["selected"]))}
        self.assertTrue(evaluate(base, reversed_answer)["success"])

    def test_planning_oracle_matches_independent_bitmask_search(self):
        task = self.task("planning")
        public = task["public"]
        ids = [p["id"] for p in public["projects"]]
        best = 0
        for mask in range(1 << len(ids)):
            selected = [p for i, p in enumerate(ids) if mask & (1 << i)]
            if not _planning_feasibility(public, selected):
                best = max(best, _planning_value(public, selected))
        self.assertEqual(best, task["private"]["optimal_value"])

    def test_planning_constraints_and_duplicates(self):
        task = self.task("planning")
        self.assertTrue(validate_public(task, {"selected": ["P1", "P1"]}))
        self.assertTrue(validate_public(task, {"selected": ["NONEXISTENT"]}))
        self.assertTrue(validate_public(task, {"selected": [p["id"] for p in task["public"]["projects"]]}))

    def test_sequential_cancel_dedup_rejection_frozen_and_condition(self):
        public = {"initial_balances": {"A": 100, "B": 20, "C": 0}, "initial_frozen": [],
                  "events": [
                      {"id": "E1", "op": "transfer", "from": "A", "to": "B", "amount": 50},
                      {"id": "E2", "op": "debit", "account": "C", "amount": 10},
                      {"id": "E3", "op": "credit", "account": "C", "amount": 30},
                      {"id": "E2", "op": "debit", "account": "C", "amount": 10},
                      {"id": "E4", "op": "freeze", "account": "B"},
                      {"id": "E5", "op": "transfer", "from": "A", "to": "B", "amount": 10},
                      {"id": "E6", "op": "credit", "account": "B", "amount": 5},
                      {"id": "E7", "op": "bonus_if", "account": "C", "if_account": "A",
                       "threshold": 100, "amount": 7},
                      {"id": "C1", "op": "cancel", "target": "E1"}]}
        expected = {"balances": {"A": 100, "B": 25, "C": 37}, "frozen": ["B"], "accepted": 4}
        self.assertEqual(expected, _sequential_answer(public))

    def test_sequential_frozen_order_irrelevant(self):
        task = self.task("sequential")
        answer = copy.deepcopy(task["private"]["answer"])
        answer["frozen"].reverse()
        self.assertTrue(evaluate(task, answer)["success"])
        answer["accepted"] += 1
        self.assertFalse(evaluate(task, answer)["success"])
        self.assertEqual([], validate_public(task, answer))

    def test_invalid_outputs_do_not_crash(self):
        cases = [None, [], {}, {"facts": []}, {"selected": [None]},
                 {"balances": [], "frozen": [[]], "accepted": True}]
        for task, answer in itertools.product(self.tasks, cases):
            with self.subTest(family=task["family"], answer=answer):
                result = evaluate(task, answer)
                self.assertFalse(result["success"])
                self.assertTrue(0 <= result["score"] <= 1)


if __name__ == "__main__":
    unittest.main()
