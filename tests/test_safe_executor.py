"""Host process must remain responsive even if native container operations hang."""
import copy
import io
import json
import time
import types
import unittest
from unittest.mock import patch

from orgbench.code_tasks import (CandidateError, evaluate_code, run_candidate,
                                 validate_code_public)
from orgbench.safe_executor import (MEMORY_LIMIT_BYTES, STDOUT_LIMIT_BYTES,
                                    SafeExecutionError, SafeExecutorInfrastructureError,
                                    _worker, run_isolated)


DAG_COMPARISON = """def solve(payload):
    a = [0]
    b = [0]
    for i in range(31):
        a = [a, a]
        b = [b, b]
    return a == b
"""


class SafeExecutorTests(unittest.TestCase):
    def test_worker_isolation_and_memory_policy_installed(self):
        policy = run_isolated({"operation": "policy"})
        self.assertTrue(policy["memory_limit_enforced"])
        self.assertEqual(256 * 1024 * 1024, policy["process_memory_limit_bytes"])
        self.assertEqual(MEMORY_LIMIT_BYTES, policy["process_memory_limit_bytes"])
        self.assertEqual(STDOUT_LIMIT_BYTES, policy["stdout_limit_bytes"])
        self.assertEqual(1, policy["python_isolated"])
        self.assertEqual(1, policy["python_no_site"])
        self.assertFalse(policy["environment_has_api_secrets"])

    def test_native_dag_compare_hits_host_hard_timeout(self):
        started = time.monotonic()
        with self.assertRaisesRegex(SafeExecutionError, "hard timeout"):
            run_isolated({"operation": "run", "source": DAG_COMPARISON, "payload": {}}, timeout_s=.8)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual({"alive": True}, run_candidate("def solve(payload):\n    return {'alive': True}", {}))

    def test_run_candidate_uses_hard_isolation_too(self):
        started = time.monotonic()
        with self.assertRaisesRegex(CandidateError, "hard timeout"):
            run_candidate(DAG_COMPARISON, {})
        self.assertLess(time.monotonic() - started, 7.0)

    def test_parent_stdout_cap(self):
        source = "def solve(payload):\n    return {'x': 'x' * 2000}"
        with self.assertRaisesRegex(SafeExecutionError, "output limit"):
            run_isolated({"operation": "run", "source": source, "payload": {}}, stdout_limit=128)

    def test_worker_input_cap(self):
        with self.assertRaisesRegex(SafeExecutionError, "input exceeds"):
            run_isolated({"operation": "run", "source": "def solve(payload):\n    return {}", "payload": {"x": "x" * 2100000}})

    def test_mutation_rejected_even_with_correct_return_value(self):
        source = "def solve(payload):\n    payload['x'].append(2)\n    return {'answer': 1}"
        payload = {"x": [1]}
        before = copy.deepcopy(payload)
        with self.assertRaisesRegex(CandidateError, "Input mutation forbidden"):
            run_candidate(source, payload)
        self.assertEqual(before, payload)
        case = {"payload": payload, "expected": {"answer": 1}}
        task = {"public": {"examples": [case]}, "private": {"cases": [case]}}
        for result in (validate_code_public(task, {"source": source}), evaluate_code(task, {"source": source})):
            self.assertFalse(result["success"])
            self.assertTrue(any("mutation" in v for v in result["violations"]))

    def test_type_none_and_bound_method_sorted_key(self):
        source = "def solve(payload):\n    d = {'a': 2, 'b': 1}\n    return {'is_none': isinstance(None, type(None)), 'keys': sorted(d, key=d.get)}"
        self.assertEqual({"is_none": True, "keys": ["b", "a"]}, run_candidate(source, {}))

    def test_augassign_evaluates_side_effecting_index_once(self):
        source = """def solve(payload):
    a = [0, 10]
    c = [0]
    def k():
        v = c[0]
        c[0] += 1
        return v
    a[k()] += 1
    return {'a': a, 'calls': c[0]}
"""
        self.assertEqual({"a": [1, 10], "calls": 1}, run_candidate(source, {}))

    def test_aggregate_json_output_bomb_fails_without_host_memory_growth(self):
        source = "def solve(payload):\n    a = [0]*4096\n    return [a]*4096"
        started = time.monotonic()
        with self.assertRaises(CandidateError):
            run_candidate(source, {})
        self.assertLess(time.monotonic() - started, 3.0)

    def test_infrastructure_failure_propagates_distinct_public_hidden_flags(self):
        case = {"payload": {}, "expected": {}}
        task = {"public": {"examples": [case]}, "private": {"cases": [case]}}
        with patch("orgbench.safe_executor.run_isolated", side_effect=SafeExecutorInfrastructureError("resource policy unavailable")):
            public = validate_code_public(task, {"source": "def solve(payload):\n    return {}"})
            hidden = evaluate_code(task, {"source": "def solve(payload):\n    return {}"})
            self.assertTrue(public["executor_infrastructure_error"])
            self.assertTrue(public["validator_error"])
            self.assertTrue(hidden["executor_infrastructure_error"])
            with self.assertRaises(SafeExecutorInfrastructureError):
                run_candidate("def solve(payload):\n    return {}", {})
        with patch("orgbench.safe_executor.run_isolated", side_effect=SafeExecutionError("Isolated worker hard timeout")):
            failure = validate_code_public(task, {"source": "def solve(payload):\n    return {}"})
            self.assertNotIn("executor_infrastructure_error", failure)
            self.assertNotIn("validator_error", failure)

    def test_child_policy_install_failure_is_truthfully_reported(self):
        output = io.BytesIO()
        with patch("orgbench.safe_executor._memory_limit", side_effect=SafeExecutorInfrastructureError("job installation failed")):
            with patch("orgbench.safe_executor.sys.stdout", types.SimpleNamespace(buffer=output)):
                _worker()
        envelope = json.loads(output.getvalue())
        self.assertFalse(envelope["ok"])
        self.assertFalse(envelope["memory_limit_enforced"])
        self.assertTrue(envelope["executor_infrastructure_error"])

    def test_os_process_startup_failure_is_infrastructure(self):
        with patch("orgbench.safe_executor.subprocess.Popen", side_effect=OSError("simulated startup failure")):
            with self.assertRaises(SafeExecutorInfrastructureError):
                run_isolated({"operation": "policy"})

    def test_corrupt_worker_ipc_is_infrastructure(self):
        process = types.SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(b"not-json"),
                                        stderr=io.BytesIO(), returncode=0,
                                        wait=lambda timeout=None: None, kill=lambda: None)
        with patch("orgbench.safe_executor.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(SafeExecutorInfrastructureError, "invalid IPC JSON"):
                run_isolated({"operation": "policy"})


if __name__ == "__main__":
    unittest.main()
