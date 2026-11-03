"""Infrastructure recovery may change registration, never the frozen treatment."""
import json
from pathlib import Path
import tempfile
import unittest

from analysis.recovery_lineage import digest, sha, verify


class RecoveryLineageTests(unittest.TestCase):
    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def fixture(self, root):
        dev, new, old = (root / name for name in ("dev", "new", "old"))
        for directory, protocol in ((dev, "original protocol"), (new, "recovery protocol")):
            source = directory / "sources/orgbench/example.py"
            source.parent.mkdir(parents=True)
            source.write_text("# frozen solver\n", encoding="utf-8")
            (directory / "protocol.md").write_text(protocol, encoding="utf-8")
        code = digest({"example.py": sha(dev / "sources/orgbench/example.py")})
        settings = dict(model="test", thinking="disabled", temperature_request=.3,
                        temperature_effective=.3, workers=4, repeats=1,
                        max_calls=5, max_output_tokens=12000, max_input_tokens=32000,
                        api_base_url="https://example.test")
        old_plan = {"holdout": {"seed": 7}, **settings}
        new_plan = {"holdout": {"seed": 8}, **settings}
        self.write(dev / "plan.json", old_plan)
        self.write(new / "plan.json", new_plan)
        data = [{"task": i} for i in range(81)]
        (dev / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in data), encoding="utf-8")
        self.write(dev / "run_state.json", {"complete": True})
        cfg = {**settings, "code_hash": code, "protocol_hash": sha(dev / "protocol.md"), "plan_hash": digest(old_plan)}
        dm = {"config": cfg}
        self.write(dev / "manifest.json", dm)
        arms = ["single_tool", "single_self_review", "hierarchy_tool", "best_of_three", "adaptive_tools"]
        parent = dict(candidate="adaptive_tools", architectures=arms, ranking=[{"name": "adaptive_tools"}],
                      rule="frozen rule", development_results_hash=digest(data),
                      **{k: cfg[k] for k in ("code_hash", "protocol_hash", "plan_hash")})
        self.write(dev / "selection.json", parent)
        failed = [{"status": "provider_error"}]
        self.write(old / "manifest.json", {"config": {"seed": 7}})
        (old / "results.jsonl").write_text(json.dumps(failed[0]) + "\n", encoding="utf-8")
        (old / "INVALIDATED.md").write_text("Do not resume.", encoding="utf-8")
        amendment = dict(schema_version="v6-infrastructure-amendment-v1", quality_based_changes=False,
                         candidate_unchanged=True, original_development_manifest_modified=False,
                         parent_selection_file="dev/selection.json", parent_selection_hash=digest(parent),
                         parent_development_manifest_hash=digest(dm), parent_development_results_hash=digest(data),
                         parent_protocol_hash=cfg["protocol_hash"], parent_plan_hash=cfg["plan_hash"],
                         new_protocol_hash=sha(new / "protocol.md"), new_plan_hash=digest(new_plan),
                         code_hash=code, candidate="adaptive_tools", architectures=arms,
                         new_confirmation_seed=8, expected_tasks=60, expected_cells=300,
                         old_confirmation_directory="old", old_confirmation_results_hash=digest(failed),
                         old_confirmation_cells=1, old_confirmation_infrastructure_errors=1)
        self.write(root / "amendment.json", amendment)
        selected = {**parent, "protocol_hash": amendment["new_protocol_hash"],
                    "plan_hash": amendment["new_plan_hash"], "parent_selection_hash": digest(parent),
                    "amendment_hash": digest(amendment)}
        self.write(new / "selection.json", selected)
        cc = {**settings, "code_hash": code, "protocol_hash": selected["protocol_hash"],
              "plan_hash": selected["plan_hash"], "selection_hash": digest(selected),
              "architectures": arms, "seed": 8, "per_family": 20}
        self.write(new / "manifest.json", {"config": cc})
        return dev, new

    def check(self, root, dev, new):
        return verify(root, dev, new, new / "selection.json", root / "amendment.json")

    def test_valid_recovery_retains_parent_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); dev, new = self.fixture(root)
            self.assertTrue(self.check(root, dev, new)["valid"])

    def test_changed_treatment_is_rejected(self):
        for field, value, reason in (("candidate", "contract_team", "same_candidate"),
                                      ("rule", "new quality rule", "same_rule")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); dev, new = self.fixture(root)
                selected = json.loads((new / "selection.json").read_text())
                selected[field] = value; self.write(new / "selection.json", selected)
                result = self.check(root, dev, new)
                self.assertFalse(result["valid"]); self.assertIn(reason, result["errors"])

    def test_parent_results_or_new_protocol_cannot_change(self):
        for target in ("dev/results.jsonl", "new/protocol.md"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); dev, new = self.fixture(root)
                with (root / target).open("a", encoding="utf-8") as stream:
                    stream.write('{"task":999}\n')
                self.assertFalse(self.check(root, dev, new)["valid"])

    def test_old_failure_cannot_be_silently_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); dev, new = self.fixture(root)
            (root / "old/INVALIDATED.md").unlink()
            result = self.check(root, dev, new)
            self.assertFalse(result["valid"])
            self.assertIn("old_failure_retained", result["errors"])


if __name__ == "__main__":
    unittest.main()
