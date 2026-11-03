import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from orgbench.primary import analyze


class PrimaryValidityTests(unittest.TestCase):
    def test_invalidated_complete_data_never_becomes_a_confirmed_winner(self):
        names = ["single", "single_refine", "hierarchy", "adaptive", "artifact_single", "artifact_contracts", "contract_adaptive"]
        config = {"architectures": names, "seed": 20261104, "thinking": "enabled", "split": "holdout", "per_family": 10,
                  "repeats": 2, "max_calls": 5, "max_output_tokens": 12000, "max_input_tokens": 24000,
                  "workers": 24, "input_run_cap": 4000000, "output_run_cap": 5200000,
                  "timeout_per_call_s": 240, "model": "deepseek-v4-pro", "protocol_hash": "test"}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            folder = Path(temp)
            (folder / "manifest.json").write_text(json.dumps({"config": config}), encoding="utf-8")
            public = [{"id": str(i)} for i in range(30)]
            (folder / "tasks.public.json").write_text(json.dumps(public), encoding="utf-8")
            rows = [{"task_id": task["id"], "architecture": arch, "repeat": rep, "family": "test",
                     "status": "ok", "evaluation": {"success": arch == "contract_adaptive", "score": float(arch == "contract_adaptive")}}
                    for task in public for arch in names for rep in range(2)]
            (folder / "results.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            (folder / "INVALIDATED.md").write_text("Infrastructure contamination", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                analyze(folder)
            result = json.loads((folder / "primary.json").read_text(encoding="utf-8"))
            self.assertTrue(result["complete"])
            self.assertFalse(result["valid_for_confirmation"])
            for comparison in result["primary_comparisons_holm_family_of_three"].values():
                self.assertLess(comparison["p_holm"], .05)
                self.assertFalse(comparison["confirmed_quality_improvement"])


if __name__ == "__main__":
    unittest.main()
