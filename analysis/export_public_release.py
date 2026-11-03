"""Build a local, reviewable release using explicit paths and field projections.

This command never calls a model, publishes, initializes Git, or copies a run
directory. v5 results are reconstructed as metrics-only cells. v6 remains pending
unless an explicit completion flag passes the archived-study validation gate.
"""
# Legacy research-workspace exporter: emits the original audit layout.
# Export only to a fresh review directory, not over this curated checkout.
# archive/path-map.json documents the current reader-facing destination layout.
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any


DOC_ALLOWLIST = (
    "protocol_v4.md", "protocol_v5.md", "literature_audit.md",
    "roadmap_evaluation_v6.md", "task_architecture_matrix_v5.md",
    "v5_independent_confirmation_audit.md",
)
PRESERVED_FILES = frozenset({
    "README.md", "README.zh-CN.md", "CONTRIBUTING.md", "LICENSE-NOTICE.md", ".gitattributes",
    "LICENSE", ".gitignore", "pyproject.toml", "requirements.txt", ".github/workflows/ci.yml",
    "docs/architecture_catalog.md", "docs/evaluation.md", "docs/data_cards.md",
    "docs/reproduce.md", "docs/limitations.md",
    "docs/data-policy.md", "docs/methods.md", "docs/release-checklist.md",
    "docs/reproducibility.md", "docs/results-v5.md", "docs/study-status.md",
    "docs/results-v6.md",
    "docs/task_examples.md", "docs/conclusions.md", "docs/known_limitations.md", "docs/release_review.md",
    "examples/public_demo_tasks.json", "datasets/README.md",
    "datasets/v5/tasks.public.json", "datasets/v6r1/tasks.public.json",
    "results/v6/confirmation_success.png", "results/v6/task_family_heatmap.png",
    "results/v6/paired_quality_deltas.png",
    # This is a public reproduction template, not the active registration.
    # Do not overwrite it with the root protocol's active held-out seeds.
    "docs/protocol_v6.md",
    # Same separation for the public, user-chosen-seed reproduction plan.
    "docs/study_v6_plan.json",
})
V5_RESULTS = Path("runs/tools_holdout_v5/results.jsonl")
V5_SOURCE_SNAPSHOT = Path("runs/tools_holdout_v5/sources/orgbench")
V6_DEV = Path("runs/tools_dev_v6")
V6_HOLDOUT = Path("runs/tools_holdout_v6")
V6_CONTROLS = frozenset({"single_tool", "single_self_review", "hierarchy_tool", "best_of_three"})
V6_CANDIDATES = frozenset({"bazaar_tool", "contract_team", "adaptive_tools", "evidence_gated"})
V6_ARCHITECTURES = V6_CONTROLS | V6_CANDIDATES | {"plain_single"}
V6_FAMILIES = frozenset({"code_config", "code_ledger", "code_versions"})
FORBIDDEN_COMPONENT = re.compile(r"(?:^|[._-])(?:auth|api|traces?|aes|billing|account|private)(?:$|[._-])", re.I)
IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{24,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{24,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_.-]{24,}\b", re.I),
    re.compile(r'''["']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)["']?\s*[:=]\s*["'][A-Za-z0-9_./+=-]{20,}["']''', re.I),
)
ENV_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.I)
LOCAL_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:[\\/][^\s`\"<>\)\]]+")
LOCAL_POSIX_PATH = re.compile(r"(?<![\w:/])/(?:Users|home|root|tmp|private|workspace|mnt|var)/[^\s`\"<>\)\]]+")

# Exact public aggregate schema. Unknown keys are dropped at every depth.
# Architecture/family names and rule-value keys are part of this public schema.
BREAKDOWN_KEYS = frozenset("""
schema_version client_research_date study scope source_fingerprints code_hash
suite_hash protocol_hash selection_hash grid independent_tasks architectures
cells repeats export_policy aggregate_public_rule_metrics_only answers_exported
prompts_exported hidden_test_payloads_exported api_logs_or_request_identifiers_exported
analysis_policy new_hypothesis_tests threshold_search frozen_threshold_unchanged
strata_overlap signature_singletons_do_not_support_generalization
routing_documentation_note frozen_protocol_text_scores actual_public_spec_and_trace_scores
uniform_immutable_spec_must_marker_adds_one_verified threshold25_routes_unchanged
interpretation preexisting_confirmatory_decision confirmed_quality_improvement_vs_all_baselines
confirmed_efficiency_improvement note overall independent_task_count paired_contrasts
families code_config code_ledger code_versions frozen_route_feature_strata
public_rule_value_strata full_public_semantic_signature_strata mechanism_contrast
same_single_algorithm_tasks contract_team_vs_single_treated_tasks
descriptive_traditional_architecture_counterexamples hierarchy_over_adaptive_public_rule_groups
hierarchy_success_single_and_adaptive_failed_singleton_tasks warnings single_tool
adaptive_tools hierarchy_tool contract_team adaptive_minus_hierarchy adaptive_minus_single
hierarchy_minus_single authority baseline baseline_only_success bonus_comparison both_failure
both_success cache_read_input_tokens calls cancel candidate candidate_only_success
completed_hidden_only_failure completed_success complexity_score condition_context
conditional_markers count_noop_freeze credit_frozen dedup dependencies dependency_markers
effective_organization_counts failure_class_counts family feature final_public_failure_hint_cell_counts
first_public_passed_cells frozen_public_route_features identical_initial_model_prompt_pairs
input_tokens keys mean_calls mean_calls_difference mean_input_tokens mean_official_score
mean_official_score_difference mean_output_tokens merge model_max_tokens_cells null
observed_success_rate_difference ok output_mismatch output_tokens paired_tasks primitive_rule_values
priority priority_order public_failed_attempts public_failure_repairs public_hint_ever_cell_counts
public_rule public_rules public_test_failure public_tests_failed public_value qualified_retractions
retraction_scope runtime_error same_effective_algorithm_pairs semantic_signature status_counts
success_rate successes syntax_or_unsupported_subset tasks tie total_input_token_difference
total_output_token_difference total_token_ratio total_tokens transfer_requires_unfrozen_destination
unknown_usage_cells unknown_usage_pairs
""".split())

# Counts, statistical comparisons and fixed method labels only. No row-error
# text, task examples, source, traces, prompts, request IDs or arbitrary notes.
V6_STAT_KEYS = frozenset("""
analysis_version candidate primary_control secondary_controls required_arms expectation_mode
expected_tasks expected_repeats expected_cells observed_rows valid_unique_cells complete
valid_for_confirmation decision_blockers validation missing_cell_count duplicate_cell_count
unexpected_cell_count infrastructure_cells unknown_usage_cells actual_overrun_cells invalidated
primary_comparison secondary_comparisons_holm_family_of_three confirmed_primary_quality_improvement
confirmed_secondary_quality_improvements must_win_all_controls summary family_exploratory
fwer_allocation primary_single_comparison secondary_holm_family_of_three nominal_total
tasks cells successes success_rate mean_score mean_tokens input_tokens_observed output_tokens_observed
cache_read_input_tokens_observed calls usage_complete overrun_cells missing_arm_data descriptive_only
no_confirmatory_subgroup_claims independent_tasks unadjusted_exploratory_paired_comparisons
baseline delta ci95 p_two_sided permutation_method exact_permutation token_ratio family_alpha
multiplicity confirmed_quality_improvement comparison_blocker p_holm holm_family_size paired_tasks
ratio undefined_bootstrap_samples efficiency_confirmation metric method unavailable_reason
ci95_task_cluster ci95_hoeffding_conservative input_tokens output_tokens tokens_per_success
mean_wall_s p95_wall_s errors families code_hash protocol_hash plan_hash development_results_hash
architectures ranking name tokens
""".split()) | V6_ARCHITECTURES | V6_FAMILIES


class ExportError(RuntimeError):
    """A safe diagnostic code without source data, keys, or credential values."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _safe_relative(path: Path) -> bool:
    return (not path.is_absolute() and ".." not in path.parts
            and all(not part.startswith(".env") and not FORBIDDEN_COMPONENT.search(part)
                    for part in path.parts))


def _regular_source(root: Path, relative: Path) -> Path:
    """Do not follow symlinks or traverse outside the designated workspace."""
    if not _safe_relative(relative):
        raise ExportError("forbidden_source_path")
    path = root / relative
    for part in [path, *path.parents]:
        if part == root:
            break
        if part.is_symlink():
            raise ExportError("source_symlink_rejected")
    if not path.resolve().is_relative_to(root):
        raise ExportError("source_outside_workspace")
    if not path.is_file():
        raise ExportError("source_not_regular_file")
    return path


def _contains_secret(data: bytes) -> bool:
    """Return only a boolean; never log a matched token or an env value."""
    text = data.decode("utf-8", errors="replace")
    if any(pattern.search(text) is not None for pattern in SECRET_PATTERNS):
        return True
    return any(len(value) >= 12 and value in text
               for name, value in os.environ.items() if ENV_SECRET_NAME.search(name))


def _sanitize_text(text: str) -> str:
    return LOCAL_POSIX_PATH.sub("[local-path-omitted]",
                                LOCAL_WINDOWS_PATH.sub("[local-path-omitted]", text))


def _aggregate_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _aggregate_projection(item) for key, item in value.items()
                if key in BREAKDOWN_KEYS}
    if isinstance(value, list):
        return [_aggregate_projection(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ExportError("invalid_aggregate_value")


def _stat_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stat_projection(item) for key, item in value.items() if key in V6_STAT_KEYS}
    if isinstance(value, list):
        return [_stat_projection(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ExportError("invalid_v6_statistic")


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ExportError("invalid_cell_identifier")
    return value


def _metric(value: Any, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    if type(value) not in ((int,) if integer else (int, float)):
        raise ExportError("invalid_cell_metric")
    if value < 0 or not math.isfinite(value):
        raise ExportError("invalid_cell_metric")
    return value


def sanitize_cell(row: dict) -> dict:
    """Construct a cell from a field allowlist; no answer/error/trace copies."""
    if not isinstance(row, dict):
        raise ExportError("invalid_cell_record")
    evaluation = row.get("evaluation", {})
    if not isinstance(evaluation, dict):
        raise ExportError("invalid_cell_evaluation")
    score = _metric(evaluation.get("score"))
    if score is not None and score > 1:
        raise ExportError("invalid_cell_score")
    success = evaluation.get("success")
    result = {key: _identifier(row.get(key)) for key in ("task_id", "family", "architecture", "status")}
    result["repeat"] = _metric(row.get("repeat"), integer=True)
    result["evaluation"] = {"success": success if type(success) is bool else None, "score": score}
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "calls"):
        result[key] = _metric(row.get(key), integer=True)
    result["wall_s"] = _metric(row.get("wall_s"))
    result["usage_complete"] = row.get("usage_complete") is True
    return result


def _digest(value: Any) -> str:
    # Matches the registered runner's canonical JSON digest, including spaces.
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _archive_json(root: Path, relative: Path) -> Any:
    try:
        return json.loads(_regular_source(root, relative).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError):
        raise ExportError("v6_invalid_archive_json") from None


def _archive_rows(root: Path, relative: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in _regular_source(root, relative).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    except (json.JSONDecodeError, UnicodeError):
        raise ExportError("v6_invalid_archive_results") from None


def _source_snapshot(root: Path, directory: Path) -> tuple[str, dict[str, bytes]]:
    sources = {}
    for source in sorted((root / directory).glob("*.py")):
        sources[source.name] = _regular_source(root, source.relative_to(root)).read_bytes()
    if not sources:
        raise ExportError("v6_source_archive_missing")
    return _digest({name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}), sources


def _validate_v6_grid(rows: list[dict], tasks: Any, arms: set[str], per_family: int, config: dict) -> list[dict]:
    if (not isinstance(tasks, list) or len(tasks) != per_family * 3
            or config.get("repeats") != 1 or config.get("per_family") != per_family):
        raise ExportError("v6_registered_grid_mismatch")
    task_families = {_identifier(task.get("id")): _identifier(task.get("family"))
                     for task in tasks if isinstance(task, dict)}
    if (len(task_families) != len(tasks)
            or Counter(task_families.values()) != Counter({family: per_family for family in V6_FAMILIES})):
        raise ExportError("v6_public_task_grid_mismatch")
    expected = {(task, arm, 0) for task in task_families for arm in arms}
    cells, seen = [], set()
    for row in rows:
        cell = sanitize_cell(row)
        identity = (cell["task_id"], cell["architecture"], cell["repeat"])
        if identity not in expected or identity in seen or cell["family"] != task_families[cell["task_id"]]:
            raise ExportError("v6_duplicate_or_unexpected_cell")
        seen.add(identity)
        if (cell["usage_complete"] is not True or type(cell["evaluation"]["success"]) is not bool
                or cell["evaluation"]["score"] is None
                or any(cell[key] is None for key in ("calls", "input_tokens", "output_tokens", "cache_read_input_tokens", "wall_s"))
                or cell["cache_read_input_tokens"] > cell["input_tokens"]):
            raise ExportError("v6_unknown_usage_or_invalid_cell")
        if (cell["status"] in {"provider_error", "execution_error", "evaluator_error"}
                or row.get("executor_infrastructure_error")
                or row.get("evaluation", {}).get("executor_infrastructure_error")
                or row.get("public_feedback", {}).get("executor_infrastructure_error")
                or row.get("public_feedback", {}).get("validator_error")):
            raise ExportError("v6_infrastructure_contamination")
        if (any(row.get(key) for key in ("accounting_unknown", "usage_unknown", "transport_rejection_usage_unknown", "invalidated"))
                or row.get("actual_input_budget_exceeded") is not False
                or row.get("actual_output_budget_exceeded") is not False
                or (cell["evaluation"]["success"] and cell["status"] not in {"ok", "success"})):
            raise ExportError("v6_invalid_execution_or_usage")
        budget = row.get("budget", {})
        for metric, limit in (("calls", "max_calls"), ("input_tokens", "max_input_tokens"),
                              ("output_tokens", "max_output_tokens")):
            if (type(config.get(limit)) is not int or config[limit] < 1
                    or budget.get(limit) != config[limit] or cell[metric] > config[limit]):
                raise ExportError("v6_resource_budget_mismatch_or_overrun")
        cells.append(cell)
    if seen != expected or len(rows) != len(expected):
        raise ExportError("v6_incomplete_registered_grid")
    return cells


def _check_v6_summary(summary: Any, cells: list[dict], arms: set[str], *, decision=False) -> None:
    if not isinstance(summary, dict) or set(summary) != arms:
        raise ExportError("v6_summary_arm_mismatch")
    for arm in arms:
        rows = [row for row in cells if row["architecture"] == arm]
        expected = {"cells": len(rows), "tasks": len({row["task_id"] for row in rows}),
                    "successes": sum(row["evaluation"]["success"] for row in rows),
                    "calls": sum(row["calls"] for row in rows),
                    "input_tokens_observed" if decision else "input_tokens": sum(row["input_tokens"] for row in rows),
                    "output_tokens_observed" if decision else "output_tokens": sum(row["output_tokens"] for row in rows)}
        if not isinstance(summary[arm], dict) or any(summary[arm].get(key) != value for key, value in expected.items()):
            raise ExportError("v6_summary_metrics_mismatch")


def _public_task_projection(root, relative, count):
    tasks = _archive_json(root, relative)
    if not isinstance(tasks, list) or len(tasks) != count:
        raise ExportError("retired_public_task_count_mismatch")
    projected = []
    for task in tasks:
        if not isinstance(task, dict) or "private" in task:
            raise ExportError("private_task_projection_rejected")
        projected.append({key: task[key] for key in ("id", "family", "split", "prompt", "schema", "public")})
    return (json.dumps(projected, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _completed_v6_payloads(root: Path, *, development_dir=V6_DEV, confirmation_dir=V6_HOLDOUT, selection_file=None, amendment_file=None, include_public_tasks=False) -> tuple[dict[str, bytes], dict]:
    """Only exact completed, valid archives cross this gate, including null results."""
    dev_dir, confirm_dir = Path(development_dir), Path(confirmation_dir)
    selection_path = Path(selection_file) if selection_file else dev_dir / "selection.json"
    lineage = None
    state = {"state": "invalid", "valid_for_confirmation": False, "results_exported": False,
             "requested_completed_export": True, "invalid_reasons": []}
    try:
        run_state = _archive_json(root, confirm_dir / "run_state.json")
        if (run_state.get("complete") is not True or run_state.get("executed_cells") != 300
                or run_state.get("expected_cells") != 300 or run_state.get("infrastructure_circuit_latched") is not False):
            raise ExportError("v6_confirmation_not_complete")
        decision = _archive_json(root, confirm_dir / "decision.json")
        if decision.get("valid_for_confirmation") is not True:
            raise ExportError("v6_confirmation_decision_invalid")
        if (decision.get("complete") is not True or decision.get("expected_tasks") != 60
                or decision.get("expected_cells") != 300 or decision.get("expected_repeats") != 1
                or decision.get("observed_rows") != 300 or decision.get("valid_unique_cells") != 300
                or decision.get("decision_blockers") != []
                or any(decision.get(key) != 0 for key in ("infrastructure_cells", "unknown_usage_cells", "actual_overrun_cells"))
                or decision.get("invalidated") is not False):
            raise ExportError("v6_decision_grid_or_validity_mismatch")
        secondary = {"single_tool", "hierarchy_tool", "best_of_three"}
        declarations = decision.get("confirmed_secondary_quality_improvements", {})
        if (decision.get("expectation_mode") != "exact_planned_task_ids"
                or decision.get("primary_control") != "single_self_review"
                or set(decision.get("secondary_controls", [])) != secondary
                or type(decision.get("confirmed_primary_quality_improvement")) is not bool
                or not isinstance(declarations, dict) or set(declarations) != secondary
                or any(type(value) is not bool for value in declarations.values())):
            raise ExportError("v6_decision_registration_mismatch")
        validation = decision.get("validation", {})
        if (not isinstance(validation, dict) or validation.get("row_errors") != []
                or any(validation.get(key) != 0 for key in (
                    "missing_cell_count", "duplicate_cell_count", "unexpected_cell_count"))):
            raise ExportError("v6_decision_validation_mismatch")
        dev_state = _archive_json(root, dev_dir / "run_state.json")
        if (dev_state.get("complete") is not True or dev_state.get("executed_cells") != 81
                or dev_state.get("expected_cells") != 81 or dev_state.get("infrastructure_circuit_latched") is not False):
            raise ExportError("v6_development_not_complete")
        config = {split: _archive_json(root, directory / "manifest.json")["config"]
                  for split, directory in (("dev", dev_dir), ("holdout", confirm_dir))}
        selection = _archive_json(root, selection_path)
        if selection.get("amendment_hash"):
            try:
                from .recovery_lineage import verify
            except ImportError:
                from recovery_lineage import verify
            amendment_path = Path(amendment_file or selection["amendment_file"])
            lineage = verify(root, root / dev_dir, root / confirm_dir, root / selection_path, root / amendment_path)
            if not lineage["valid"]:
                raise ExportError("v6_recovery_lineage_invalid")
        candidate = selection.get("candidate")
        arms = V6_CONTROLS | {candidate} if isinstance(candidate, str) else set()
        if (candidate not in V6_CANDIDATES or set(selection.get("architectures", [])) != arms
                or len(selection.get("architectures", [])) != 5
                or set(config["holdout"].get("architectures", [])) != arms
                or len(config["holdout"].get("architectures", [])) != 5
                or set(config["dev"].get("architectures", [])) != V6_ARCHITECTURES
                or decision.get("candidate") != candidate or set(decision.get("required_arms", [])) != arms
                or len(decision.get("required_arms", [])) != 5
                or config["holdout"].get("selection_hash") != _digest(selection)):
            raise ExportError("v6_frozen_selection_mismatch")
        archive_hashes, snapshots, protocols, plans = {}, {}, {}, {}
        for split, directory in (("dev", dev_dir), ("holdout", confirm_dir)):
            cfg = config[split]
            source_hash, snapshots[split] = _source_snapshot(root, directory / "sources/orgbench")
            protocols[split] = _regular_source(root, directory / "protocol.md").read_bytes()
            plans[split] = _regular_source(root, directory / "plan.json").read_bytes()
            plan = _archive_json(root, directory / "plan.json")
            selection_reference = lineage["parent_selection"] if lineage and split == "dev" else selection
            hashes = {"code_hash": source_hash, "protocol_hash": hashlib.sha256(protocols[split]).hexdigest(),
                      "plan_hash": _digest(plan)}
            if (cfg.get("split") != split or any(cfg.get(key) != value or selection_reference.get(key) != value
                                                     for key, value in hashes.items())
                    or any(cfg.get(key) != plan.get(key) for key in (
                        "repeats", "workers", "max_calls", "max_input_tokens", "max_output_tokens", "model", "thinking"))
                    or cfg.get("per_family") != plan.get(split, {}).get("per_family")
                    or cfg.get("seed") != plan.get(split, {}).get("seed")):
                raise ExportError("v6_source_protocol_plan_hash_mismatch")
            archive_hashes[split] = hashes
        if ((lineage and archive_hashes["dev"]["code_hash"] != archive_hashes["holdout"]["code_hash"])
                or (not lineage and (archive_hashes["dev"] != archive_hashes["holdout"]
                    or protocols["dev"] != protocols["holdout"] or plans["dev"] != plans["holdout"]))):
            raise ExportError("v6_development_confirmation_archives_differ")
        rows = {split: _archive_rows(root, directory / "results.jsonl")
                for split, directory in (("dev", dev_dir), ("holdout", confirm_dir))}
        if selection.get("development_results_hash") != _digest(rows["dev"]):
            raise ExportError("v6_development_selection_results_mismatch")
        cells = {}
        summaries = {}
        for split, directory, split_arms, per_family in (("dev", dev_dir, V6_ARCHITECTURES, 3),
                                                       ("holdout", confirm_dir, arms, 20)):
            tasks = _archive_json(root, directory / "tasks.public.json")
            cells[split] = _validate_v6_grid(rows[split], tasks, split_arms, per_family, config[split])
            summaries[split] = _archive_json(root, directory / "summary.json")
            _check_v6_summary(summaries[split], cells[split], split_arms)
        _check_v6_summary(decision.get("summary"), cells["holdout"], arms, decision=True)
        payloads = {}
        for split in ("dev", "holdout"):
            payloads[f"results/v6/{split}_cells.jsonl"] = b"".join(
                (json.dumps(cell, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8") for cell in cells[split])
            payloads[f"results/v6/{split}_summary.json"] = _json_bytes(_stat_projection(summaries[split]))
        payloads["results/v6/decision.json"] = _json_bytes(_stat_projection(decision))
        payloads["results/v6/selection.json"] = _json_bytes(_stat_projection(selection))
        payloads["docs/protocol_v6_original.md"] = protocols["holdout"]
        payloads["docs/study_v6_plan_original.json"] = plans["holdout"]
        if include_public_tasks:
            payloads["datasets/v6r1/tasks.public.json"] = _public_task_projection(root, confirm_dir / "tasks.public.json", 60)
            payloads["datasets/v5/tasks.public.json"] = _public_task_projection(root, Path("runs/tools_holdout_v5/tasks.public.json"), 90)
        chart = Path("results/v6r1/quality_tokens.png" if lineage else "results/v6/quality_tokens.png")
        if (root / chart).exists():
            data = _regular_source(root, chart).read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 4 * 1024 * 1024:
                raise ExportError("v6_invalid_metrics_plot")
            payloads["results/v6/quality_tokens.png"] = data
        if lineage:
            payloads["docs/protocol_v6_development_original.md"] = protocols["dev"]
            payloads["docs/study_v6_development_plan_original.json"] = plans["dev"]
            payloads["results/v6/recovery_amendment.json"] = _json_bytes(lineage["amendment"])
            payloads["results/v6/parent_selection.json"] = _json_bytes(lineage["parent_selection"])
        for name, data in snapshots["holdout"].items():
            payloads["historical/v6/orgbench/" + name] = data
        state = {"state": "completed", "valid_for_confirmation": True, "results_exported": True,
                 "recovery_confirmation": bool(lineage),
                 "failed_prior_confirmation_cells_excluded": 49 if lineage else 0,
                 "dev_cells": 81, "holdout_cells": 300, "frozen_candidate": candidate,
                 "development_results_are_exploratory": True, "confirmation_independent_tasks": 60,
                 "confirmed_primary_quality_improvement": decision["confirmed_primary_quality_improvement"],
                 "confirmed_secondary_quality_improvements": _stat_projection(decision["confirmed_secondary_quality_improvements"]),
                 "archive_hashes": archive_hashes["holdout"],
                 "original_plan_file_sha256": hashlib.sha256(plans["holdout"]).hexdigest(),
                 "frozen_source_files": len(snapshots["holdout"]),
                 "resource_analysis": "Descriptive only; v6 defines no efficiency-confirmation claim."}
        payloads["results/v6/report.json"] = _json_bytes(state)
        return payloads, state
    except ExportError as exc:
        state["invalid_reasons"] = [str(exc)]
    except (KeyError, TypeError, ValueError, AttributeError, OSError):
        state["invalid_reasons"] = ["v6_archive_missing_or_malformed"]
    return {}, state


def _allowed_destination(relative: Path, planned: set[str]) -> bool:
    name = relative.as_posix()
    if not _safe_relative(relative):
        return False
    return name in planned or name in PRESERVED_FILES or name == "release_manifest.json"


def _existing_files(destination: Path, planned: set[str]) -> dict[str, bytes]:
    existing = {}
    if not destination.exists():
        return existing
    # This recursion is restricted to the export target, never the workspace/runs.
    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        if path.is_symlink():
            raise ExportError("destination_symlink_rejected")
        allowed = planned | PRESERVED_FILES | {"release_manifest.json"}
        if not _safe_relative(relative) or (path.is_dir() and not any(
                name.startswith(relative.as_posix() + "/") for name in allowed)):
            raise ExportError("unapproved_existing_release_directory")
        if path.is_file():
            if not _allowed_destination(relative, planned):
                raise ExportError("unapproved_existing_release_file")
            content = path.read_bytes()
            if _contains_secret(content):
                raise ExportError("sensitive_content_detected")
            existing[relative.as_posix()] = content
    return existing


def export_release(source_root: Path | str, destination: Path | str | None = None, *,
                   include_completed_v6: bool = False, development_dir=V6_DEV, confirmation_dir=V6_HOLDOUT,
                   selection_file=None, amendment_file=None, include_public_tasks=False) -> dict:
    root = Path(source_root).resolve()
    target = Path(destination) if destination is not None else root / "release" / "agent-org-bench"
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
        raise ExportError("destination_symlink_rejected")
    target = target.resolve()
    if target == root or root.is_relative_to(target):
        raise ExportError("unsafe_export_destination")
    if target.is_relative_to(root) and target.relative_to(root).parts[0] in {
            "orgbench", "tests", "analysis", "docs", "results", "runs"}:
        raise ExportError("unsafe_export_destination")
    payloads: dict[str, bytes] = {}
    missing_docs = []
    # Only shallow, explicit Python globs. No rglob/copytree of source trees.
    for directory, pattern in (("orgbench", "*.py"), ("tests", "test*.py")):
        for path in sorted((root / directory).glob(pattern)):
            if directory == "tests" and path.name.startswith("test_v7"):
                continue
            relative = path.relative_to(root)
            if _safe_relative(relative):
                payloads[relative.as_posix()] = _regular_source(root, relative).read_bytes()
    historical_count = 0
    # One explicitly named frozen archive, shallow Python files only. This is
    # separate from current code and does not assert matching version hashes.
    for path in sorted((root / V5_SOURCE_SNAPSHOT).glob("*.py")):
        relative = path.relative_to(root)
        if _safe_relative(relative):
            output = Path("historical/v5/orgbench") / path.name
            payloads[output.as_posix()] = _regular_source(root, relative).read_bytes()
            historical_count += 1
    for name in DOC_ALLOWLIST:
        relative = Path("docs") / name
        if not (root / relative).exists():
            missing_docs.append(name)
            continue
        text = _regular_source(root, relative).read_text(encoding="utf-8")
        payloads[relative.as_posix()] = _sanitize_text(text).encode("utf-8")
    exporter = Path("analysis/export_public_release.py")
    if (root / exporter).exists():
        payloads[exporter.as_posix()] = _regular_source(root, exporter).read_bytes()
    lineage_helper = Path("analysis/recovery_lineage.py")
    if (root / lineage_helper).exists():
        payloads[lineage_helper.as_posix()] = _regular_source(root, lineage_helper).read_bytes()
    replay = Path("analysis/analyze_public_results.py")
    if (root / replay).exists():
        payloads[replay.as_posix()] = _regular_source(root, replay).read_bytes()
    figures = Path("analysis/make_public_figures.py")
    if (root / figures).exists():
        payloads[figures.as_posix()] = _regular_source(root, figures).read_bytes()
    breakdown = Path("results/v5/task_breakdown.json")
    if (root / breakdown).exists():
        try:
            raw = json.loads(_regular_source(root, breakdown).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError):
            raise ExportError("invalid_aggregate_json") from None
        payloads[breakdown.as_posix()] = _json_bytes(_aggregate_projection(raw))
    cells = []
    if (root / V5_RESULTS).exists():
        result_path = _regular_source(root, V5_RESULTS)
        with result_path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    cells.append(sanitize_cell(json.loads(line)))
                except (json.JSONDecodeError, UnicodeError):
                    raise ExportError("invalid_results_jsonl") from None
        payloads["results/v5/cells.jsonl"] = b"".join(
            (json.dumps(cell, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8") for cell in cells)
    v6_state = {
        "state": "pending", "results_exported": False,
        "reason": "Completed v6 export was not requested; no partial cells are published."}
    if include_completed_v6:
        v6_payloads, v6_state = _completed_v6_payloads(root, development_dir=development_dir, confirmation_dir=confirmation_dir, selection_file=selection_file, amendment_file=amendment_file, include_public_tasks=include_public_tasks)
        payloads.update(v6_payloads)
    payloads["results/v6/state.json"] = _json_bytes(v6_state)
    # Preflight all planned and preserved contents before writing even one file.
    existing = _existing_files(target, set(payloads))
    if any(_contains_secret(content) for content in payloads.values()):
        raise ExportError("sensitive_content_detected")
    combined = {**existing, **payloads}
    combined.pop("release_manifest.json", None)
    records = [{"path": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
               for name, content in sorted(combined.items())]
    manifest = {"schema_version": "public-release-allowlist-v1", "publication_state": "local_review_only",
                "v6_state": v6_state["state"], "private_tasks_exported": False,
                "answers_exported": False, "raw_runs_copied": False,
                "source_results_projection": "explicit_v5_results_jsonl_field_allowlist",
                "v5_cells": len(cells), "missing_optional_docs": missing_docs,
                "historical_v5_source_files": historical_count,
                "current_source_is_distinct_from_frozen_v5_snapshot": True,
                "active_v6_protocol_exported": False,
                "completed_v6_export_requested": include_completed_v6,
                "v6_original_archives_exported": v6_state["state"] == "completed",
                "v6_confirmation_valid": v6_state.get("valid_for_confirmation", False),
                "sensitive_content_scan_passed": True, "files": records,
                "manifest_self_hash_excluded": True}
    for name, content in payloads.items():
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
    (target / "release_manifest.json").write_bytes(_json_bytes(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--dev", type=Path, default=V6_DEV)
    parser.add_argument("--confirm", type=Path, default=V6_HOLDOUT)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--amendment", type=Path)
    parser.add_argument("--include-public-tasks", action="store_true")
    parser.add_argument("--include-completed-v6", action="store_true",
                        help="Opt in to audited completed v6 archives; invalid/incomplete studies export an invalid state only")
    args = parser.parse_args()
    try:
        manifest = export_release(args.root, args.destination, include_completed_v6=args.include_completed_v6,
                                  development_dir=args.dev, confirmation_dir=args.confirm,
                                  selection_file=args.selection, amendment_file=args.amendment,
                                  include_public_tasks=args.include_public_tasks)
    except ExportError as exc:
        # ExportError messages are fixed codes and never contain file contents.
        parser.exit(2, "Release export rejected: " + str(exc) + "\n")
    print(json.dumps({"publication_state": manifest["publication_state"],
                      "files": len(manifest["files"]), "v5_cells": manifest["v5_cells"],
                      "v6_state": manifest["v6_state"], "sensitive_content_scan_passed": True}))


if __name__ == "__main__":
    main()
