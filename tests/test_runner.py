import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from orgbench import run as runner


def args(**overrides):
    values = dict(out="run", split="dev", per_family=1, seed=7, repeats=1,
                  architectures="single", max_calls=5, max_output_tokens=3600,
                  max_input_tokens=24000, model="test-model", workers=1,
                  input_run_cap=4000000, output_run_cap=500000, prepare_only=True,
                  thinking="disabled", protocol="docs/protocol.md")
    values.update(overrides)
    return argparse.Namespace(**values)


class RunnerTests(unittest.TestCase):
    def test_late_success_does_not_reopen_latched_failure_circuit(self):
        class FakeProvider:
            totals = {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as path:
            root = Path(path)
            (root / "docs").mkdir()
            (root / "docs" / "protocol.md").write_text("fixed", encoding="utf-8")
            (root / "orgbench").mkdir()
            tasks = [{"id": str(i), "family": "evidence", "prompt": "public", "private": {}} for i in range(20)]
            count = [0]
            lock = threading.Lock()
            def fake_run(*unused, **kwargs):
                with lock:
                    count[0] += 1
                    index = count[0]
                time.sleep(.2 if index == 2 else .005)
                return {"status": "ok" if index == 2 else "provider_error", "answer": {}, "trace": [], "calls": 1, "input_tokens": 1, "output_tokens": 1}
            with patch.object(runner, "ROOT", root), patch.object(runner, "generate_suite", return_value=tasks), patch.object(runner.Provider, "from_env", return_value=FakeProvider()), patch.object(runner, "run_architecture", side_effect=fake_run), patch.object(runner, "evaluate", return_value={"success": True, "score": 1., "violations": []}), contextlib.redirect_stdout(io.StringIO()):
                runner.run(args(prepare_only=False, workers=2))
            self.assertEqual(count[0], 6)
            state = json.loads((root / "run" / "run_state.json").read_text(encoding="utf-8"))
            self.assertTrue(state["infrastructure_circuit_latched"])
            self.assertFalse(state["complete"])

    def test_incompatible_resume_preserves_original_task_files(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as path:
            root = Path(path)
            (root / "docs").mkdir()
            (root / "docs" / "protocol.md").write_text("fixed", encoding="utf-8")
            (root / "orgbench").mkdir()
            task = {"id": "t", "family": "evidence", "prompt": "public", "private": {"answer": "secret"}}
            with patch.object(runner, "ROOT", root), patch.object(runner, "generate_suite", return_value=[task]), contextlib.redirect_stdout(io.StringIO()):
                runner.run(args())
                original = (root / "run" / "tasks.private.json").read_bytes()
                with self.assertRaisesRegex(ValueError, "configuration/code differs"):
                    runner.run(args(seed=8))
                self.assertEqual(original, (root / "run" / "tasks.private.json").read_bytes())
                public = json.loads((root / "run" / "tasks.public.json").read_text(encoding="utf-8"))
                self.assertNotIn("private", public[0])

    def test_interrupted_jsonl_is_reported_and_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as path:
            log = Path(path) / "results.jsonl"
            data = '{"complete":true}\n{"incomplete":'
            log.write_text(data, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 2"):
                runner.read_rows(log)
            self.assertEqual(log.read_text(encoding="utf-8"), data)

    def test_incomplete_organization_is_not_scored_as_completed_success(self):
        class FakeProvider:
            totals = {"attempts": 1, "successes": 1, "input_tokens": 10, "output_tokens": 10}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as path:
            root = Path(path)
            (root / "docs").mkdir()
            (root / "docs" / "protocol.md").write_text("fixed", encoding="utf-8")
            (root / "orgbench").mkdir()
            task = {"id": "t", "family": "evidence", "prompt": "public", "private": {"answer": {"facts": {}}}}
            def fake_run(name, public_task, provider, **kwargs):
                self.assertNotIn("private", public_task)
                return {"status": "budget_exhausted", "answer": {"facts": {}}, "trace": [], "calls": 1, "input_tokens": 10, "output_tokens": 10}
            with patch.object(runner, "ROOT", root), patch.object(runner, "generate_suite", return_value=[task]), patch.object(runner.Provider, "from_env", return_value=FakeProvider()), patch.object(runner, "run_architecture", side_effect=fake_run), patch.object(runner, "evaluate", return_value={"success": True, "score": 1., "violations": []}), contextlib.redirect_stdout(io.StringIO()):
                runner.run(args(prepare_only=False))
            row = runner.read_rows(root / "run" / "results.jsonl")[0]
            self.assertFalse(row["evaluation"]["success"])
            self.assertTrue(row["best_effort_evaluation"]["success"])


if __name__ == "__main__":
    unittest.main()
