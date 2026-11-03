import json
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orgbench import study_v6


class FrozenSelectionTests(unittest.TestCase):
    def fixture(self, directory):
        config = {"split": "dev", "code_hash": "frozen", "protocol_hash": "protocol", "plan_hash": "plan",
                  "architectures": list(study_v6.DESCRIPTIONS), "repeats": 1}
        (directory / "manifest.json").write_text(json.dumps({"config": config}))
        (directory / "tasks.public.json").write_text(json.dumps([{"id": "task"}]))
        rows = [{"task_id": "task", "architecture": name, "repeat": 0,
                 "status": "ok", "usage_complete": True,
                 "evaluation": {"success": True}, "input_tokens": 100,
                 "output_tokens": 1 if name in study_v6.CONTROLS else 50}
                for name in study_v6.DESCRIPTIONS]
        for row in rows:
            if row["architecture"] == "contract_team":
                row["output_tokens"] = 2
        self.write_rows(directory, rows)
        return rows

    def write_rows(self, directory, rows):
        (directory / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_controls_never_enter_candidate_selection(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(study_v6, "code_digest", return_value="frozen"), patch("builtins.print"):
            directory = Path(temp)
            self.fixture(directory)
            selection = study_v6.freeze_selection(directory)
            self.assertEqual(selection["candidate"], "contract_team")
            self.assertEqual(set(selection["architectures"]), {*study_v6.CONTROLS, "contract_team"})
            self.assertNotIn("plain_single", selection["architectures"])

    def test_missing_or_usage_unknown_cannot_select(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(study_v6, "code_digest", return_value="frozen"):
            directory = Path(temp)
            rows = self.fixture(directory)
            self.write_rows(directory, rows[:-1])
            with self.assertRaises(ValueError):
                study_v6.freeze_selection(directory)
            rows[0]["usage_complete"] = False
            self.write_rows(directory, rows)
            with self.assertRaises(ValueError):
                study_v6.freeze_selection(directory)

    def test_selection_is_immutable(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(study_v6, "code_digest", return_value="frozen"), patch("builtins.print"):
            directory = Path(temp)
            rows = self.fixture(directory)
            selected = study_v6.freeze_selection(directory)
            self.assertEqual(selected, study_v6.freeze_selection(directory))
            rows[0]["output_tokens"] += 1
            self.write_rows(directory, rows)
            with self.assertRaises(ValueError):
                study_v6.freeze_selection(directory)


class RegisteredPlanTests(unittest.TestCase):
    def setup_plan(self, split="holdout"):
        plan = {"dev": {"seed": 6, "per_family": 3}, "holdout": {"seed": 7, "per_family": 20},
                "thinking": "disabled", "repeats": 1, "workers": 4, "max_calls": 5,
                "max_output_tokens": 12000, "max_input_tokens": 32000, "model": "test"}
        args = SimpleNamespace(split=split, seed=None, per_family=None,
                               **{k: v for k, v in plan.items() if k not in ("dev", "holdout", "model")})
        return args, plan

    def test_confirmation_defaults_resolve_to_registered_holdout(self):
        args, plan = self.setup_plan()
        study_v6.registered_parameters(args, plan, [*study_v6.CONTROLS, "contract_team"], "test")
        self.assertEqual((args.seed, args.per_family), (7, 20))

    def test_wrong_sample_or_arm_list_rejected(self):
        args, plan = self.setup_plan()
        args.per_family = 3
        with self.assertRaises(ValueError):
            study_v6.registered_parameters(args, plan, [*study_v6.CONTROLS, "contract_team"], "test")
        args, plan = self.setup_plan()
        with self.assertRaises(ValueError):
            study_v6.registered_parameters(args, plan, ["single_tool", "hierarchy_tool", "contract_team"], "test")

    def test_wrong_model_or_budget_rejected(self):
        args, plan = self.setup_plan("dev")
        with self.assertRaises(ValueError):
            study_v6.registered_parameters(args, plan, list(study_v6.DESCRIPTIONS), "other")
        args.max_calls = 4
        with self.assertRaises(ValueError):
            study_v6.registered_parameters(args, plan, list(study_v6.DESCRIPTIONS), "test")

    def test_endpoint_identity_is_sensitive_to_service_change_and_rejects_credentials(self):
        with patch.dict("os.environ", {"ANTHROPIC_BASE_URL": "https://a.example/v1"}):
            first = study_v6.endpoint_identity()
        with patch.dict("os.environ", {"ANTHROPIC_BASE_URL": "https://b.example/v1"}):
            self.assertNotEqual(first, study_v6.endpoint_identity())
        with patch.dict("os.environ", {"ANTHROPIC_BASE_URL": "https://name:password@example.com"}):
            with self.assertRaises(ValueError):
                study_v6.endpoint_identity()


if __name__ == "__main__":
    unittest.main()
