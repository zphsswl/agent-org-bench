import copy
import inspect
import json
import time
import unittest

from orgbench.code_tasks import (
    CandidateError, CODE_FAMILIES, _config_reference, _ledger_reference,
    _versions_reference, evaluate_code, generate_code_suite, run_candidate,
    validate_code_public,
)


def trusted_reference_as_candidate(task):
    # Test the interpreter against the trusted Python implementation. This
    # source exists only in test code, and is never included in model prompts.
    functions = {"code_versions": _versions_reference,
                 "code_ledger": _ledger_reference,
                 "code_config": _config_reference}
    function = functions[task["family"]]
    source = inspect.getsource(function)
    original = source.splitlines()[0]
    source = source.replace(original, "def solve(payload):\n    rules = RULES", 1)
    return "RULES = " + repr(task["public"]["rules"]) + "\n\n" + source


class CodeTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = generate_code_suite(per_family=2)

    def test_deterministic_suites_and_disjoint_splits(self):
        self.assertEqual(self.tasks, generate_code_suite(per_family=2))
        holdout = generate_code_suite(split="holdout", per_family=2)
        self.assertTrue({t["id"] for t in self.tasks}.isdisjoint(t["id"] for t in holdout))
        self.assertTrue({t["prompt"] for t in self.tasks}.isdisjoint(t["prompt"] for t in holdout))
        self.assertEqual(6, len(self.tasks))

    def test_case_counts_and_semantics_not_only_numeric_variants(self):
        for task in self.tasks:
            self.assertEqual(3, len(task["public"]["examples"]))
            self.assertEqual(30, len(task["private"]["cases"]))
            self.assertEqual(30, len({json.dumps(c["payload"], sort_keys=True) for c in task["private"]["cases"]}))
            self.assertEqual(task["family"], next(f for f in CODE_FAMILIES if f == task["family"]))
        for family in CODE_FAMILIES:
            signatures = {t["metadata"]["semantic_signature"] for t in self.tasks if t["family"] == family}
            self.assertEqual(2, len(signatures))

    def test_trusted_reference_passes_all_public_and_hidden(self):
        for task in self.tasks:
            answer = {"source": trusted_reference_as_candidate(task)}
            with self.subTest(task=task["id"]):
                public = validate_code_public(task, answer)
                hidden = evaluate_code(task, answer)
                self.assertTrue(public["success"], public)
                self.assertTrue(hidden["success"], hidden)
                self.assertEqual(30, hidden["hidden_passed"])

    def test_deliberately_wrong_starters_fail(self):
        for task in self.tasks:
            answer = {"source": task["public"]["starter_source"]}
            with self.subTest(task=task["id"]):
                self.assertFalse(validate_code_public(task, answer)["success"])
                self.assertFalse(evaluate_code(task, answer)["success"])

    def test_public_boundary_does_not_read_private(self):
        for task in self.tasks:
            public_task = {k: copy.deepcopy(v) for k, v in task.items() if k != "private"}
            answer = {"source": trusted_reference_as_candidate(task)}
            self.assertTrue(validate_code_public(public_task, answer)["success"])
        task = copy.deepcopy(self.tasks[0])
        answer = {"source": trusted_reference_as_candidate(task)}
        first = validate_code_public(task, answer)
        task["private"] = {"cases": [{"payload": {}, "expected": "CORRUPTED"}]}
        self.assertEqual(first, validate_code_public(task, answer))

    def test_hardcoding_public_examples_does_not_pass_hidden(self):
        for task in self.tasks:
            examples = task["public"]["examples"]
            source = "EXAMPLES = " + repr(examples) + "\ndef solve(payload):\n    for case in EXAMPLES:\n        if payload == case['payload']:\n            return case['expected']\n    return {}\n"
            answer = {"source": source}
            self.assertTrue(validate_code_public(task, answer)["success"])
            self.assertFalse(evaluate_code(task, answer)["success"])

    def test_version_rules_handcrafted_authority_ties_delete_retraction(self):
        payload = {"cutoff": 5, "records": [
            {"id": "D10", "kind": "set", "key": "Key", "value": "old", "time": 1, "authority": 3},
            {"id": "D2", "kind": "set", "key": "key", "value": "new", "time": 4, "authority": 1},
            {"id": "D3", "kind": "delete", "key": "gone", "time": 5, "authority": 2},
            {"id": "R", "kind": "retract", "target": "D10", "time": 2, "authority": 2}]}
        rules = {"keys": "lower", "authority": "higher", "priority": "authority_then_time",
                 "tie": "id_lex", "qualified_retractions": True, "retraction_scope": "global"}
        self.assertEqual({"values": {"key": "old"}, "sources": {"key": "D10", "gone": "D3"}},
                         _versions_reference(payload, rules))
        rules["qualified_retractions"] = False
        self.assertEqual("new", _versions_reference(payload, rules)["values"]["key"])
        payload["records"][3]["time"] = 0
        rules["retraction_scope"] = "not_after_retractor"
        self.assertEqual("old", _versions_reference(payload, rules)["values"]["key"])

    def test_version_lexical_id_tie_is_not_numeric(self):
        rules = {"keys": "case_sensitive", "authority": "higher", "priority": "time_then_authority",
                 "tie": "id_lex", "qualified_retractions": False, "retraction_scope": "global"}
        payload = {"cutoff": 5, "records": [
            {"id": "D10", "kind": "set", "key": "x", "value": 10, "time": 1, "authority": 1},
            {"id": "D2", "kind": "set", "key": "x", "value": 2, "time": 1, "authority": 1}]}
        self.assertEqual(2, _versions_reference(payload, rules)["values"]["x"])
        rules["tie"] = "first"
        self.assertEqual(10, _versions_reference(payload, rules)["values"]["x"])

    def test_ledger_retry_semantics_and_global_forward_cancel(self):
        rules = {"cancel": "global", "dedup": "first_seen", "credit_frozen": True,
                 "transfer_requires_unfrozen_destination": True, "count_noop_freeze": True,
                 "bonus_comparison": "ge"}
        payload = {"initial": {"A": 0, "B": 5}, "frozen": [], "events": [
            {"id": "x", "op": "debit", "account": "A", "amount": 2},
            {"id": "x", "op": "credit", "account": "A", "amount": 3},
            {"id": "y", "op": "credit", "account": "B", "amount": 1},
            {"id": "c", "op": "cancel", "target": "y"}]}
        self.assertEqual({"balances": {"A": 0, "B": 5}, "frozen": [], "accepted": []},
                         _ledger_reference(payload, rules))
        rules.update(dedup="first_applied", cancel="forward")
        self.assertEqual({"balances": {"A": 3, "B": 6}, "frozen": [], "accepted": ["x", "y"]},
                         _ledger_reference(payload, rules))

    def test_config_revisit_condition_and_null_semantics(self):
        rules = {"keys": "lower", "priority_order": "ascending", "tie": "input",
                 "dependencies": "revisit", "condition_context": "live", "null": "delete", "merge": "overwrite"}
        payload = {"defaults": {"Mode": "off", "gone": 1}, "layers": [
            {"id": "a", "priority": 0, "requires": ["b"], "when": {"key": "mode", "op": "eq", "equals": "on"}, "values": {"x": 1}},
            {"id": "b", "priority": 1, "requires": [], "when": None, "values": {"Mode": "on", "gone": None}},
            {"id": "cycle", "priority": 2, "requires": ["cycle"], "when": None, "values": {"x": 99}}]}
        expected = {"config": {"mode": "on", "x": 1}, "applied": ["b", "a"], "blocked": ["cycle"]}
        self.assertEqual(expected, _config_reference(payload, rules))
        rules["dependencies"] = "single_pass"
        self.assertEqual(["a", "cycle"], _config_reference(payload, rules)["blocked"])
        rules.update(dependencies="revisit", condition_context="snapshot", null="literal")
        out = _config_reference(payload, rules)
        self.assertEqual(["b"], out["applied"])
        self.assertIsNone(out["config"]["gone"])

    def test_interpreter_helper_lambda_comprehension_and_no_input_mutation(self):
        source = """def solve(payload):
    def rank(x):
        return (-x['value'], x['id'])
    rows = [dict(x) for x in payload['rows'] if x.get('value', 0) >= 0]
    rows.sort(key=rank)
    counts = {}
    for x in rows:
        counts[x['id']] = counts.get(x['id'], 0) + 1
    return {'ids': [x['id'] for x in rows], 'counts': counts, 'total': sum(x['value'] for x in rows)}
"""
        payload = {"rows": [{"id": "b", "value": 1}, {"id": "a", "value": 1}, {"id": "z", "value": -1}]}
        before = copy.deepcopy(payload)
        self.assertEqual({"ids": ["a", "b"], "counts": {"a": 1, "b": 1}, "total": 2}, run_candidate(source, payload))
        self.assertEqual(before, payload)

    def test_generator_short_circuit_is_lazy(self):
        source = "def solve(payload):\n    return {'found': any(row['ok'] or row['missing'] for row in payload['rows'])}\n"
        self.assertEqual({'found': True}, run_candidate(source, {'rows': [{'ok': True}, {'ok': False}]}))

    def test_reject_host_capability_escapes(self):
        sources = [
            "import os\ndef solve(payload):\n    return {}",
            "def solve(payload):\n    return open('secret').read()",
            "def solve(payload):\n    return eval('1+1')",
            "def solve(payload):\n    return payload.__class__",
            "def solve(payload):\n    return getattr(payload, '__class__')",
            "class X:\n    pass\ndef solve(payload):\n    return {}",
            "@print\ndef solve(payload):\n    return {}",
            "SIDE = solve({})\ndef solve(payload):\n    return {}",
            "def solve(payload):\n    print('hello')\n    return {}",
            "def solve(payload):\n    try:\n        return {}\n    except:\n        return {}",
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(CandidateError):
                run_candidate(source, {})

    def test_fuel_recursion_and_memory_output_bounds(self):
        sources = [
            "def solve(payload):\n    while True:\n        pass",
            "def solve(payload):\n    return solve(payload)",
            "def solve(payload):\n    return [0] * 1000000000",
            "def solve(payload):\n    return 'x' * 1000000000",
            "def solve(payload):\n    return 9 ** 999999999",
            "def solve(payload):\n    a = {}\n    a['a'] = a\n    return a",
            "def solve(payload):\n    a = []\n    for i in range(1000):\n        a.append([0]*4096)\n    return {}",
            "def solve(payload):\n    a = [0]*4096\n    b = [a]*4096\n    return sum(b, [])",
            "def solve(payload):\n    a = [0]*4096\n    b = [a]*4096\n    return f'{b}'",
            "def solve(payload):\n    a = [0]*4096\n    return [a]*4096",
        ]
        started = time.monotonic()
        for source in sources:
            with self.subTest(source=source), self.assertRaises(CandidateError):
                run_candidate(source, {})
        self.assertLess(time.monotonic() - started, 3.0)

    def test_syntax_failure_keeps_public_denominator(self):
        for answer in ({}, {"source": "not valid python @"}, None):
            result = validate_code_public(self.tasks[0], answer)
            self.assertFalse(result["valid_syntax"])
            self.assertEqual(3, result["public_total"])
            self.assertEqual(0, result["public_passed"])

    def test_hidden_failure_feedback_omits_expected_values(self):
        result = evaluate_code(self.tasks[0], {"source": "def solve(payload):\n    return {}"})
        self.assertFalse(result["success"])
        self.assertTrue(result["violations"])
        self.assertNotIn("expected", json.dumps(result))

    def test_bool_is_not_integer_answer(self):
        task = copy.deepcopy(self.tasks[0])
        task["public"]["examples"] = [{"payload": {}, "expected": {"value": 1}}]
        result = validate_code_public(task, {"source": "def solve(payload):\n    return {'value': True}"})
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
