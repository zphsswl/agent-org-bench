"""Offline release allowlist checks; fixtures never contain real credentials."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analysis.export_public_release import (DOC_ALLOWLIST, ExportError, export_release,
                                            sanitize_cell, V6_ARCHITECTURES, V6_CONTROLS,
                                            _public_task_projection)


class ReleaseExportTests(unittest.TestCase):
    def test_retired_task_projection_preserves_input_mapping_order(self):
        with tempfile.TemporaryDirectory(dir=self.temp_base) as temp:
            root = Path(temp).resolve()
            task = {"id": "demo", "family": "code_config", "split": "holdout", "prompt": "public",
                    "schema": {}, "metadata": {"not_exported": True},
                    "public": {"examples": [{"payload": {"patch": {"b": 2, "a": 1}}, "expected": {}}]}}
            (root / "tasks.public.json").write_text(json.dumps([task]), encoding="utf-8")
            exported = json.loads(_public_task_projection(root, Path("tasks.public.json"), 1))
            self.assertNotIn("metadata", exported[0])
            self.assertEqual(list(exported[0]["public"]["examples"][0]["payload"]["patch"]), ["b", "a"])

    def test_retired_task_projection_rejects_private_case_container(self):
        with tempfile.TemporaryDirectory(dir=self.temp_base) as temp:
            root = Path(temp).resolve()
            (root / "tasks.public.json").write_text(json.dumps([{"private": {"cases": []}}]))
            with self.assertRaises(ExportError):
                _public_task_projection(root, Path("tasks.public.json"), 1)

    def test_retired_task_projection_rejects_wrong_count(self):
        with tempfile.TemporaryDirectory(dir=self.temp_base) as temp:
            root = Path(temp).resolve()
            (root / "tasks.public.json").write_text("[]")
            with self.assertRaises(ExportError):
                _public_task_projection(root, Path("tasks.public.json"), 60)

    @classmethod
    def setUpClass(cls):
        # The Windows sandbox cannot write the host's default temporary folder.
        cls.temp_base = Path(__file__).resolve().parents[1] / "experimental" / "test_tmp_v6"
        cls.temp_base_was_present = cls.temp_base.exists()
        cls.temp_parent_was_present = cls.temp_base.parent.exists()
        cls.temp_base.mkdir(parents=True, exist_ok=True)
        cls.env_patch = patch.dict(os.environ, {"TEMP": str(cls.temp_base), "TMP": str(cls.temp_base)})
        cls.env_patch.start()
        cls.addClassCleanup(cls.env_patch.stop)
        cls.addClassCleanup(cls.cleanup_scratch_directories)

    @classmethod
    def cleanup_scratch_directories(cls):
        # Remove only empty directories created by this test class; a release
        # can then be re-exported without leaving a new non-allowlisted tree.
        for path, existed in ((cls.temp_base, cls.temp_base_was_present),
                              (cls.temp_base.parent, cls.temp_parent_was_present)):
            if not existed:
                try:
                    path.rmdir()
                except OSError:
                    pass

    def fixture(self):
        temporary = tempfile.TemporaryDirectory(dir=self.temp_base)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "source"
        root.mkdir()
        target = root / "release" / "agent-org-bench"

        def write(relative, content):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        write("orgbench/core.py", "# exportable implementation\n")
        write("tests/test_smoke.py", "# exportable test\n")
        write("analysis/export_public_release.py", "# exportable release utility\n")
        write("runs/tools_holdout_v5/sources/orgbench/__init__.py", "# frozen v5 package\n")
        write("runs/tools_holdout_v5/sources/orgbench/core.py", "# frozen v5 implementation\n")
        write("runs/tools_holdout_v5/sources/orgbench/nested/not_exported.py", "DO_NOT_EXPORT_NESTED_SNAPSHOT")
        write("runs/other/sources/orgbench/core.py", "DO_NOT_EXPORT_OTHER_SNAPSHOT")
        write("docs/protocol_v6.md", "# Active private registration\nACTIVE_SEED_NOT_FOR_RELEASE\n")
        for name in DOC_ALLOWLIST:
            write("docs/" + name, "# Public protocol\n[local](D:/personal/work/research.md)\n")
        write("results/v5/task_breakdown.json", json.dumps({
            "schema_version": "aggregate-v1", "overall": {"input_tokens": 10, "answer": "DROP_ME"},
            "answer": {"secret": "DROP_ME"}, "trace_file": "DROP_ME",
            "warnings": [], "scope": "aggregate public statistics only"}))
        row = {"task_id": "holdout_example_001", "family": "code_config", "architecture": "single_tool",
               "repeat": 0, "status": "ok", "evaluation": {"success": True, "score": 1.0,
               "violations": ["HIDDEN_EXPECTATION"], "hidden_passed": 30, "hidden_total": 30},
               "input_tokens": 123, "output_tokens": 45, "cache_read_input_tokens": 12,
               "calls": 2, "wall_s": 1.25, "usage_complete": True,
               "answer": {"source": "PRIVATE_SOURCE_SENTINEL"}, "trace_file": "PRIVATE_TRACE_SENTINEL",
               "error": "PRIVATE_ERROR_SENTINEL", "request_id": "PRIVATE_REQUEST_SENTINEL"}
        write("runs/tools_holdout_v5/results.jsonl", json.dumps(row) + "\n")
        # Forbidden material is deliberately present to detect accidental broad copying.
        for path in (".env", "auth/credentials.txt", "api/account.json", "billing/data.json",
                     "runs/tools_holdout_v5/tasks.private.json", "runs/tools_holdout_v5/traces/full.json",
                     "工作原则.md", "想法01.md", "docs/session_state.md", "orgbench/keys.json",
                     "orgbench/auth.py", "tests/test_api.py", "orgbench/nested/private.py",
                     "results/v6/results.jsonl"):
            write(path, "FORBIDDEN_FIXTURE_SENTINEL")
        return root, target, write, row

    def completed_v6_fixture(self):
        root, target, write, _ = self.fixture()

        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

        plan = {"model": "fixture-model", "thinking": "disabled", "workers": 4, "repeats": 1,
                "max_calls": 5, "max_input_tokens": 32000, "max_output_tokens": 12000,
                "dev": {"seed": 11, "per_family": 3}, "holdout": {"seed": 22, "per_family": 20}}
        prefixes = {"dev": "runs/tools_dev_v6/", "holdout": "runs/tools_holdout_v6/"}
        candidate = "contract_team"
        arms = set(V6_CONTROLS) | {candidate}
        configs, rows, summaries = {}, {}, {}
        for split, per_family, names in (("dev", 3, V6_ARCHITECTURES), ("holdout", 20, arms)):
            prefix = prefixes[split]
            tasks = [{"id": f"{split}_{family}_{index:03}", "family": family}
                     for family in ("code_config", "code_ledger", "code_versions") for index in range(per_family)]
            rows[split] = []
            for task in tasks:
                for name in sorted(names):
                    success = split == "dev" and name == candidate
                    rows[split].append({"task_id": task["id"], "family": task["family"], "architecture": name,
                        "repeat": 0, "status": "ok", "evaluation": {"success": success, "score": float(success),
                        "violations": ["V6_PRIVATE_EXPECTATION_SENTINEL"]}, "input_tokens": 100, "output_tokens": 20,
                        "cache_read_input_tokens": 10, "calls": 1, "wall_s": .25, "usage_complete": True,
                        "actual_input_budget_exceeded": False, "actual_output_budget_exceeded": False,
                        "budget": {key: plan[key] for key in ("max_calls", "max_input_tokens", "max_output_tokens")},
                        "answer": {"source": "V6_PRIVATE_SOURCE_SENTINEL"}, "error": "V6_PRIVATE_ERROR_SENTINEL",
                        "request_id": "V6_PRIVATE_REQUEST_SENTINEL", "trace_file": "V6_PRIVATE_TRACE_SENTINEL"})
            write(prefix + "sources/orgbench/core.py", "# frozen completed v6 implementation\n")
            source_hash = digest({"core.py": hashlib.sha256((root / (prefix + "sources/orgbench/core.py")).read_bytes()).hexdigest()})
            write(prefix + "protocol.md", "# Frozen completed original protocol\n")
            protocol_hash = hashlib.sha256((root / (prefix + "protocol.md")).read_bytes()).hexdigest()
            write(prefix + "plan.json", json.dumps(plan))
            write(prefix + "tasks.public.json", json.dumps(tasks))
            write(prefix + "tasks.private.json", "NEVER_READ_PRIVATE_V6_TASKS")
            write(prefix + "results.jsonl", "\n".join(json.dumps(row) for row in rows[split]) + "\n")
            write(prefix + "run_state.json", json.dumps({"complete": True, "executed_cells": len(rows[split]),
                                                       "expected_cells": len(rows[split]), "infrastructure_circuit_latched": False}))
            configs[split] = {key: plan[key] for key in ("repeats", "workers", "max_calls", "max_input_tokens",
                                                        "max_output_tokens", "model", "thinking")}
            configs[split].update({"split": split, "per_family": per_family, "seed": plan[split]["seed"],
                "architectures": sorted(names), "code_hash": source_hash, "protocol_hash": protocol_hash,
                "plan_hash": digest(plan), "selection_hash": None})
            summaries[split] = {}
            for name in names:
                sub = [row for row in rows[split] if row["architecture"] == name]
                summaries[split][name] = {"cells": len(sub), "tasks": len(sub),
                    "successes": sum(row["evaluation"]["success"] for row in sub), "calls": len(sub),
                    "input_tokens": len(sub) * 100, "output_tokens": len(sub) * 20,
                    "success_rate": sum(row["evaluation"]["success"] for row in sub) / len(sub),
                    "source": "V6_SUMMARY_SOURCE_SENTINEL", "error": "V6_SUMMARY_ERROR_SENTINEL"}
            write(prefix + "summary.json", json.dumps(summaries[split]))
        selection = {"candidate": candidate, "architectures": sorted(arms),
                     **{key: configs["dev"][key] for key in ("code_hash", "protocol_hash", "plan_hash")},
                     "development_results_hash": digest(rows["dev"]),
                     "ranking": [{"name": candidate, "successes": 9, "tokens": 1080}],
                     "error": "V6_SELECTION_ERROR_SENTINEL"}
        write(prefixes["dev"] + "selection.json", json.dumps(selection))
        configs["holdout"]["selection_hash"] = digest(selection)
        for split in prefixes:
            write(prefixes[split] + "manifest.json", json.dumps({"config": configs[split]}))
        decision_summary = {}
        for name, values in summaries["holdout"].items():
            decision_summary[name] = {key: value for key, value in values.items() if key in ("cells", "tasks", "successes", "calls")}
            decision_summary[name].update({"input_tokens_observed": values["input_tokens"],
                                           "output_tokens_observed": values["output_tokens"]})
        comparison = {"delta": 0.0, "ci95": [0.0, 0.0], "p_two_sided": 1.0,
                      "confirmed_quality_improvement": False, "tasks": 60, "exact_permutation": True}
        decision = {"analysis_version": "fixture-five-arm-v6", "candidate": candidate,
                    "primary_control": "single_self_review", "secondary_controls": ["single_tool", "hierarchy_tool", "best_of_three"],
                    "expectation_mode": "exact_planned_task_ids", "required_arms": sorted(arms), "complete": True,
                    "expected_tasks": 60, "expected_repeats": 1, "expected_cells": 300, "observed_rows": 300,
                    "valid_unique_cells": 300, "valid_for_confirmation": True, "decision_blockers": [],
                    "infrastructure_cells": 0, "unknown_usage_cells": 0, "actual_overrun_cells": 0, "invalidated": False,
                    "confirmed_primary_quality_improvement": False,
                    "confirmed_secondary_quality_improvements": {name: False for name in arms - {candidate, "single_self_review"}},
                    "primary_comparison": comparison, "secondary_comparisons_holm_family_of_three": {
                        name: comparison for name in arms - {candidate, "single_self_review"}}, "summary": decision_summary,
                    "validation": {"missing_cell_count": 0, "duplicate_cell_count": 0, "unexpected_cell_count": 0,
                                   "row_errors": [], "missing_cell_examples": ["DO_NOT_EXPORT_EXAMPLES"]},
                    "answer": "DO_NOT_EXPORT_DECISION_ANSWER", "error": "DO_NOT_EXPORT_DECISION_ERROR"}
        write(prefixes["holdout"] + "decision.json", json.dumps(decision))
        return root, target, write, rows, decision

    def test_allowlist_does_not_copy_private_material_or_run_directories(self):
        root, target, _, _ = self.fixture()
        manifest = export_release(root)
        names = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
        expected = {"orgbench/core.py", "tests/test_smoke.py", "analysis/export_public_release.py",
                    "historical/v5/orgbench/__init__.py", "historical/v5/orgbench/core.py",
                    "results/v5/task_breakdown.json", "results/v5/cells.jsonl", "results/v6/state.json",
                    "release_manifest.json", *("docs/" + name for name in DOC_ALLOWLIST)}
        self.assertEqual(names, expected)
        contents = "\n".join(path.read_text(encoding="utf-8") for path in target.rglob("*") if path.is_file())
        for sentinel in ("FORBIDDEN_FIXTURE_SENTINEL", "PRIVATE_SOURCE_SENTINEL", "PRIVATE_TRACE_SENTINEL",
                         "PRIVATE_ERROR_SENTINEL", "PRIVATE_REQUEST_SENTINEL", "HIDDEN_EXPECTATION", "DROP_ME"):
            self.assertNotIn(sentinel, contents)
        self.assertFalse((target / "runs").exists())
        self.assertFalse((target / ".git").exists())
        self.assertNotIn("ACTIVE_SEED_NOT_FOR_RELEASE", contents)
        self.assertNotIn("DO_NOT_EXPORT_NESTED_SNAPSHOT", contents)
        self.assertNotIn("DO_NOT_EXPORT_OTHER_SNAPSHOT", contents)
        self.assertEqual(manifest["publication_state"], "local_review_only")

    def test_frozen_v5_snapshot_is_distinct_from_current_implementation_and_hashed(self):
        root, target, _, _ = self.fixture()
        manifest = export_release(root)
        index = {entry["path"]: entry for entry in manifest["files"]}
        old = "historical/v5/orgbench/core.py"
        current = "orgbench/core.py"
        self.assertNotEqual(index[old]["sha256"], index[current]["sha256"])
        self.assertEqual(index[old]["sha256"], hashlib.sha256((target / old).read_bytes()).hexdigest())
        self.assertEqual(manifest["historical_v5_source_files"], 2)
        self.assertTrue(manifest["current_source_is_distinct_from_frozen_v5_snapshot"])

    def test_public_v6_template_is_preserved_without_active_registration_or_seeds(self):
        root, target, _, _ = self.fixture()
        template = target / "docs/protocol_v6.md"
        template.parent.mkdir(parents=True)
        template.write_text("# Public reproduction template\nChoose your own seeds.\n", encoding="utf-8")
        before = template.read_bytes()
        manifest = export_release(root)
        self.assertEqual(template.read_bytes(), before)
        self.assertFalse(manifest["active_v6_protocol_exported"])
        self.assertFalse((target / "docs/protocol_v6_original.md").exists())

    def test_public_plan_is_preserved_and_active_root_plan_is_never_exported(self):
        root, target, write, _ = self.fixture()
        write("docs/study_v6_plan.json", json.dumps({"seeds": "ACTIVE_PLAN_SEED_NOT_FOR_RELEASE"}))
        public_plan = target / "docs/study_v6_plan.json"
        public_plan.parent.mkdir(parents=True)
        public_plan.write_text(json.dumps({"study_role": "public_reproduction", "seeds": [123]}), encoding="utf-8")
        before = public_plan.read_bytes()
        manifest = export_release(root)
        self.assertEqual(public_plan.read_bytes(), before)
        index = {entry["path"]: entry for entry in manifest["files"]}
        self.assertEqual(index["docs/study_v6_plan.json"]["sha256"], hashlib.sha256(before).hexdigest())
        exported = "\n".join(path.read_text(encoding="utf-8") for path in target.rglob("*") if path.is_file())
        self.assertNotIn("ACTIVE_PLAN_SEED_NOT_FOR_RELEASE", exported)
        absent_root, absent_target, absent_write, _ = self.fixture()
        absent_write("docs/study_v6_plan.json", json.dumps({"seeds": "ACTIVE_PLAN_SEED_NOT_FOR_RELEASE"}))
        export_release(absent_root)
        self.assertFalse((absent_target / "docs/study_v6_plan.json").exists())

    def test_cells_are_an_exact_field_projection(self):
        root, target, _, row = self.fixture()
        export_release(root)
        exported = json.loads((target / "results/v5/cells.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(exported, {key: row[key] for key in (
            "task_id", "family", "architecture", "repeat", "status", "input_tokens", "output_tokens",
            "cache_read_input_tokens", "calls", "wall_s", "usage_complete")}
            | {"evaluation": {"success": True, "score": 1.0}})
        self.assertEqual(set(exported["evaluation"]), {"success", "score"})

    def test_existing_readme_workflow_and_known_docs_are_preserved_and_hashed(self):
        root, target, _, _ = self.fixture()
        preserved = {"README.md": "# Maintainer-owned README\n",
                     "README.zh-CN.md": "# 中文说明\n", "LICENSE-NOTICE.md": "License pending.\n",
                     ".github/workflows/ci.yml": "name: offline checks\n",
                     "docs/data-policy.md": "# Data policy\n", "docs/methods.md": "# Methods\n",
                     "docs/release-checklist.md": "# Local review\n", "docs/reproducibility.md": "# Reproduce\n",
                     "docs/results-v5.md": "# Historical result\n", "docs/study-status.md": "# Pending\n",
                     "docs/data_cards.md": "# Dataset cards\n", "pyproject.toml": "[project]\nname='bench'\n"}
        for name, value in preserved.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        manifest = export_release(root)
        index = {entry["path"]: entry for entry in manifest["files"]}
        for name, value in preserved.items():
            self.assertEqual((target / name).read_text(encoding="utf-8"), value)
            self.assertEqual(index[name]["sha256"], hashlib.sha256((target / name).read_bytes()).hexdigest())
        for entry in manifest["files"]:
            content = (target / entry["path"]).read_bytes()
            self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(entry["bytes"], len(content))

    def test_v6_is_pending_even_if_partial_results_are_present(self):
        root, target, _, _ = self.fixture()
        manifest = export_release(root)
        state = json.loads((target / "results/v6/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "pending")
        self.assertFalse(state["results_exported"])
        self.assertEqual(manifest["v6_state"], "pending")
        self.assertEqual(manifest["v5_cells"], 1)
        self.assertEqual(list((target / "results/v6").iterdir()), [target / "results/v6/state.json"])

    def test_markdown_local_paths_are_removed_and_link_delimiters_survive(self):
        root, target, _, _ = self.fixture()
        export_release(root)
        text = (target / "docs/protocol_v5.md").read_text(encoding="utf-8")
        self.assertNotIn("D:/personal", text)
        self.assertIn("[local]([local-path-omitted])", text)

    def test_generic_key_pattern_rejects_before_creating_target(self):
        root, target, write, _ = self.fixture()
        token = "sk-" + "A" * 32
        write("orgbench/leaked.py", "credential = '" + token + "'\n")
        with self.assertRaisesRegex(ExportError, "^sensitive_content_detected$") as caught:
            export_release(root)
        self.assertNotIn(token, str(caught.exception))
        self.assertFalse(target.exists())

    def test_actual_environment_secret_is_detected_without_echoing_value(self):
        root, target, write, _ = self.fixture()
        token = "testcredential-" + "z" * 35
        write("orgbench/leaked.py", "# " + token)
        with patch.dict(os.environ, {"RELEASE_TEST_ACCESS_TOKEN": token}):
            with self.assertRaises(ExportError) as caught:
                export_release(root)
        self.assertEqual(str(caught.exception), "sensitive_content_detected")
        self.assertNotIn(token, str(caught.exception))
        self.assertFalse(target.exists())

    def test_secrets_in_excluded_files_are_never_read_or_exported(self):
        root, target, write, _ = self.fixture()
        token = "sk-" + "B" * 32
        write(".env", token)
        write("runs/tools_holdout_v5/traces/credential.json", token)
        manifest = export_release(root)
        self.assertTrue(manifest["sensitive_content_scan_passed"])
        self.assertNotIn(token, (target / "results/v5/cells.jsonl").read_text(encoding="utf-8"))

    def test_historical_snapshot_is_secret_scanned_before_any_write(self):
        root, target, write, _ = self.fixture()
        token = "sk-" + "D" * 32
        write("runs/tools_holdout_v5/sources/orgbench/leaked.py", "# " + token)
        with self.assertRaisesRegex(ExportError, "^sensitive_content_detected$"):
            export_release(root)
        self.assertFalse(target.exists())

    def test_existing_unknown_file_or_directory_is_rejected_without_deletion(self):
        for name in ("docs/arbitrary.md", "traces", "runs"):
            with self.subTest(name=name):
                root, target, _, _ = self.fixture()
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if "." in path.name:
                    path.write_text("preserve this unapproved file", encoding="utf-8")
                else:
                    path.mkdir()
                with self.assertRaises(ExportError):
                    export_release(root)
                self.assertTrue(path.exists())
                self.assertFalse((target / "orgbench/core.py").exists())

    def test_existing_readme_is_also_secret_scanned_before_any_write(self):
        root, target, _, _ = self.fixture()
        target.mkdir(parents=True)
        (target / "README.md").write_text("sk-" + "C" * 32, encoding="utf-8")
        with self.assertRaisesRegex(ExportError, "^sensitive_content_detected$"):
            export_release(root)
        self.assertFalse((target / "orgbench/core.py").exists())

    def test_second_export_is_deterministic_and_retains_maintainer_readme(self):
        root, target, _, _ = self.fixture()
        target.mkdir(parents=True)
        (target / "README.md").write_text("# Reviewed locally\n", encoding="utf-8")
        first = export_release(root)
        first_manifest = (target / "release_manifest.json").read_bytes()
        second = export_release(root)
        self.assertEqual(first, second)
        self.assertEqual(first_manifest, (target / "release_manifest.json").read_bytes())

    def test_unsafe_destination_cannot_overwrite_source_or_raw_runs(self):
        root, _, _, _ = self.fixture()
        for destination in (root, root.parent, root / "orgbench", root / "runs" / "release"):
            with self.subTest(destination=destination), self.assertRaises(ExportError):
                export_release(root, destination)

    def test_invalid_cell_values_are_rejected_instead_of_copied_verbatim(self):
        _, _, _, row = self.fixture()
        invalid = ({"status": "error with private details"}, {"calls": -1},
                   {"wall_s": float("nan")}, {"evaluation": {"success": True, "score": 2}})
        for updates in invalid:
            with self.subTest(updates=updates), self.assertRaises(ExportError):
                sanitize_cell(row | updates)

    def test_missing_usage_is_explicitly_unknown(self):
        _, _, _, row = self.fixture()
        for key in ("calls", "input_tokens", "usage_complete"):
            row.pop(key)
        cell = sanitize_cell(row)
        self.assertIsNone(cell["calls"])
        self.assertIsNone(cell["input_tokens"])
        self.assertFalse(cell["usage_complete"])

    def assert_invalid_v6(self, root, target):
        manifest = export_release(root, include_completed_v6=True)
        state = json.loads((target / "results/v6/state.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["v6_state"], state["state"]), ("invalid", "invalid"))
        self.assertFalse(state["results_exported"])
        self.assertFalse(manifest["v6_confirmation_valid"])
        self.assertFalse((target / "results/v6/holdout_cells.jsonl").exists())
        self.assertFalse((target / "results/v6/dev_cells.jsonl").exists())
        self.assertFalse((target / "docs/protocol_v6_original.md").exists())
        self.assertFalse((target / "docs/study_v6_plan_original.json").exists())
        self.assertFalse((target / "historical/v6").exists())
        self.assertTrue(state["invalid_reasons"])
        return state

    def test_completed_valid_negative_confirmation_is_published_without_claim_rewriting(self):
        root, target, _, _, _ = self.completed_v6_fixture()
        template = target / "docs/protocol_v6.md"
        template.parent.mkdir(parents=True)
        template.write_text("# Public protocol template, choose fresh seeds.\n", encoding="utf-8")
        plan = target / "docs/study_v6_plan.json"
        plan.write_text(json.dumps({"study_role": "public_reproduction", "seed": 999}), encoding="utf-8")
        public_protocol, public_plan = template.read_bytes(), plan.read_bytes()
        manifest = export_release(root, include_completed_v6=True)
        state = json.loads((target / "results/v6/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "completed")
        self.assertTrue(state["valid_for_confirmation"])
        self.assertTrue(manifest["v6_confirmation_valid"])
        self.assertFalse(state["confirmed_primary_quality_improvement"])
        self.assertFalse(any(state["confirmed_secondary_quality_improvements"].values()))
        self.assertEqual(len((target / "results/v6/holdout_cells.jsonl").read_text().splitlines()), 300)
        self.assertEqual(len((target / "results/v6/dev_cells.jsonl").read_text().splitlines()), 81)
        self.assertEqual(template.read_bytes(), public_protocol)
        self.assertEqual(plan.read_bytes(), public_plan)
        for name, source_name in (("protocol_v6_original.md", "protocol.md"),
                                  ("study_v6_plan_original.json", "plan.json")):
            self.assertEqual((target / "docs" / name).read_bytes(),
                             (root / "runs/tools_holdout_v6" / source_name).read_bytes())
        decision = json.loads((target / "results/v6/decision.json").read_text())
        self.assertFalse(decision["confirmed_primary_quality_improvement"])
        self.assertEqual(decision["primary_comparison"]["p_two_sided"], 1.0)
        self.assertEqual((target / "historical/v6/orgbench/core.py").read_bytes(),
                         (root / "runs/tools_holdout_v6/sources/orgbench/core.py").read_bytes())
        content = "\n".join(path.read_text(encoding="utf-8") for path in target.rglob("*") if path.is_file())
        for forbidden in ("V6_PRIVATE", "V6_SUMMARY_SOURCE", "V6_SUMMARY_ERROR", "V6_SELECTION_ERROR",
                          "DO_NOT_EXPORT", "NEVER_READ_PRIVATE"):
            self.assertNotIn(forbidden, content)
        for record in manifest["files"]:
            self.assertEqual(record["sha256"], hashlib.sha256((target / record["path"]).read_bytes()).hexdigest())

    def test_default_pending_never_opens_live_v6_archives_or_copies_partial_cells(self):
        root, target, write, _, _ = self.completed_v6_fixture()
        write("runs/tools_holdout_v6/run_state.json", "deliberately unparseable live file")
        manifest = export_release(root)
        self.assertEqual(manifest["v6_state"], "pending")
        self.assertFalse((target / "results/v6/holdout_cells.jsonl").exists())
        self.assertFalse((target / "docs/study_v6_plan_original.json").exists())

    def test_completed_flag_reports_incomplete_state_and_refuses_results(self):
        root, target, write, _, _ = self.completed_v6_fixture()
        write("runs/tools_holdout_v6/run_state.json", json.dumps({"complete": False, "executed_cells": 299,
            "expected_cells": 300, "infrastructure_circuit_latched": False}))
        state = self.assert_invalid_v6(root, target)
        self.assertIn("v6_confirmation_not_complete", state["invalid_reasons"])

    def test_completed_flag_refuses_invalid_decision_even_with_full_grid(self):
        root, target, write, _, decision = self.completed_v6_fixture()
        decision["valid_for_confirmation"] = False
        decision["decision_blockers"] = ["infrastructure_contamination"]
        write("runs/tools_holdout_v6/decision.json", json.dumps(decision))
        state = self.assert_invalid_v6(root, target)
        self.assertEqual(state["invalid_reasons"], ["v6_confirmation_decision_invalid"])

    def test_complete_flag_independently_rejects_infrastructure_rows(self):
        root, target, write, rows, _ = self.completed_v6_fixture()
        rows["holdout"][0]["status"] = "provider_error"
        write("runs/tools_holdout_v6/results.jsonl", "\n".join(json.dumps(row) for row in rows["holdout"]))
        state = self.assert_invalid_v6(root, target)
        self.assertEqual(state["invalid_reasons"], ["v6_infrastructure_contamination"])

    def test_complete_flag_rejects_missing_duplicate_and_substituted_cells(self):
        for mode in ("missing", "duplicate", "substituted"):
            with self.subTest(mode=mode):
                root, target, write, rows, _ = self.completed_v6_fixture()
                if mode == "missing":
                    rows["holdout"].pop()
                elif mode == "duplicate":
                    rows["holdout"][-1] = rows["holdout"][0]
                else:
                    for row in rows["holdout"][:5]:
                        row["task_id"] = "substituted_unplanned_task"
                write("runs/tools_holdout_v6/results.jsonl", "\n".join(json.dumps(row) for row in rows["holdout"]))
                self.assert_invalid_v6(root, target)

    def test_complete_flag_requires_matching_frozen_source_protocol_and_plan(self):
        for path, content in (("sources/orgbench/core.py", "# changed source\n"),
                              ("protocol.md", "# changed registered protocol\n"),
                              ("plan.json", json.dumps({"seed": 777}))):
            with self.subTest(path=path):
                root, target, write, _, _ = self.completed_v6_fixture()
                write("runs/tools_holdout_v6/" + path, content)
                state = self.assert_invalid_v6(root, target)
                self.assertEqual(state["invalid_reasons"], ["v6_source_protocol_plan_hash_mismatch"])

    def test_complete_flag_requires_exact_frozen_selection_and_development_results(self):
        for mode in ("selection", "development_results"):
            with self.subTest(mode=mode):
                root, target, write, rows, _ = self.completed_v6_fixture()
                if mode == "selection":
                    selection = json.loads((root / "runs/tools_dev_v6/selection.json").read_text())
                    selection["candidate"] = "evidence_gated"
                    write("runs/tools_dev_v6/selection.json", json.dumps(selection))
                else:
                    rows["dev"][0]["input_tokens"] += 1
                    write("runs/tools_dev_v6/results.jsonl", "\n".join(json.dumps(row) for row in rows["dev"]))
                self.assert_invalid_v6(root, target)

    def test_completed_flag_preserves_researcher_v6_result_page(self):
        root, target, _, _, _ = self.completed_v6_fixture()
        page = target / "docs/results-v6.md"
        page.parent.mkdir(parents=True)
        page.write_text("# Independent result, including null findings\n", encoding="utf-8")
        before = page.read_bytes()
        export_release(root, include_completed_v6=True)
        self.assertEqual(page.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
