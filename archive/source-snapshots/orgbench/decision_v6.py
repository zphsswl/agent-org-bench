"""Frozen five-arm v6 quality decisions; no API or file side effects.

Primary: candidate vs single_self_review, two-sided exact paired p < .025.
Secondary: three controls, separate Holm family at .025. Each comparison has
its own declaration; beating every control is not a prerequisite for value.
Token ratios/intervals are descriptive. There is no efficiency-confirmation gate.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import math
import random
import statistics

from .statistics import paired_comparison, holm_adjust


PRIMARY = "single_self_review"
SECONDARY = ("single_tool", "hierarchy_tool", "best_of_three")
CONTROLS = (PRIMARY,) + SECONDARY
CANDIDATES = frozenset({"contract_team", "bazaar_tool", "bazaar", "adaptive_tools", "adaptive", "evidence_gated"})
INFRASTRUCTURE_STATUSES = frozenset({"provider_error", "execution_error", "evaluator_error"})
ALPHA_PRIMARY = .025
ALPHA_SECONDARY = .025
EXACT_METHOD = "exact_integer_dp_task_sign_permutation"
REQUIRED_FIELDS = (
    "task_id", "family", "architecture", "repeat", "status", "evaluation.success", "evaluation.score",
    "input_tokens", "output_tokens", "cache_read_input_tokens", "calls", "wall_s", "usage_complete",
    "actual_input_budget_exceeded", "actual_output_budget_exceeded",
    "budget.max_calls", "budget.max_input_tokens", "budget.max_output_tokens",
)


def _nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _get(row, dotted):
    value = row
    for key in dotted.split("."):
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def _known_usage(row):
    return (row["usage_complete"] is True
            and not any(row.get(k, False) for k in ("accounting_unknown", "usage_unknown", "transport_rejection_usage_unknown")))


def _row_errors(row, expected_repeats):
    if not isinstance(row, dict):
        return ["row_not_object"]
    missing = [field for field in REQUIRED_FIELDS if not _get(row, field)[0]]
    errors = ["missing_field:" + field for field in missing]
    if missing:
        return errors
    for field in ("task_id", "family", "architecture", "status"):
        if not isinstance(row[field], str) or not row[field]:
            errors.append("invalid_field:" + field)
    if type(row["repeat"]) is not int or row["repeat"] not in range(expected_repeats):
        errors.append("invalid_field:repeat")
    if type(row["evaluation"]["success"]) is not bool:
        errors.append("invalid_field:evaluation.success")
    score = row["evaluation"]["score"]
    if not _nonnegative(score) or score > 1:
        errors.append("invalid_field:evaluation.score")
    if row["evaluation"]["success"] is True and row["status"] not in ("ok", "success"):
        errors.append("success_on_incomplete_execution")
    for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "calls"):
        if type(row[field]) is not int or row[field] < 0:
            errors.append("invalid_field:" + field)
    if not _nonnegative(row["wall_s"]):
        errors.append("invalid_field:wall_s")
    for field in ("usage_complete", "actual_input_budget_exceeded", "actual_output_budget_exceeded"):
        if type(row[field]) is not bool:
            errors.append("invalid_field:" + field)
    for field in ("max_calls", "max_input_tokens", "max_output_tokens"):
        if type(row["budget"][field]) is not int or row["budget"][field] < 1:
            errors.append("invalid_field:budget." + field)
    if not errors and row["cache_read_input_tokens"] > row["input_tokens"]:
        errors.append("cache_input_exceeds_total_input")
    return errors


def _overrun(row):
    return (row["actual_input_budget_exceeded"] or row["actual_output_budget_exceeded"]
            or row["calls"] > row["budget"]["max_calls"]
            or row["input_tokens"] > row["budget"]["max_input_tokens"]
            or row["output_tokens"] > row["budget"]["max_output_tokens"])


def _summary(rows, arms):
    result = {}
    for arm in arms:
        values = [r for r in rows if r["architecture"] == arm]
        by_task = defaultdict(list)
        for row in values:
            by_task[row["task_id"]].append(row)
        if not values:
            result[arm] = {"cells": 0, "tasks": 0, "success_rate": None,
                           "mean_score": None, "mean_tokens": None,
                           "missing_arm_data": True}
            continue
        known = all(_known_usage(r) for r in values)
        result[arm] = {
            "cells": len(values), "tasks": len(by_task),
            "successes": sum(r["evaluation"]["success"] for r in values),
            "success_rate": statistics.mean(statistics.mean(float(r["evaluation"]["success"]) for r in group) for group in by_task.values()),
            "mean_score": statistics.mean(statistics.mean(r["evaluation"]["score"] for r in group) for group in by_task.values()),
            "input_tokens_observed": sum(r["input_tokens"] for r in values),
            "output_tokens_observed": sum(r["output_tokens"] for r in values),
            "cache_read_input_tokens_observed": sum(r["cache_read_input_tokens"] for r in values),
            "mean_tokens": statistics.mean(statistics.mean(r["input_tokens"] + r["output_tokens"] for r in group) for group in by_task.values()) if known else None,
            "calls": sum(r["calls"] for r in values), "usage_complete": known,
            "unknown_usage_cells": sum(not _known_usage(r) for r in values),
            "overrun_cells": sum(_overrun(r) for r in values),
            "infrastructure_cells": sum(r["status"] in INFRASTRUCTURE_STATUSES or bool(r.get("executor_infrastructure_error")) or bool(r["evaluation"].get("executor_infrastructure_error")) for r in values),
        }
    return result


def _token_ratio(a, b, *, draws, seed):
    by_arch = []
    for rows in (a, b):
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["task_id"]].append(row)
        by_arch.append(grouped)
    keys = sorted(by_arch[0].keys() & by_arch[1].keys())
    result = {"paired_tasks": len(keys), "ratio": None, "ci95": [None, None],
              "undefined_bootstrap_samples": 0, "descriptive_only": True,
              "efficiency_confirmation": "not_defined_in_v6",
              "metric": "ratio_of_total_input_plus_output_tokens", "method": "paired_task_cluster_bootstrap"}
    cost_rows = [r for groups in by_arch for key in keys for r in groups[key]]
    if not keys:
        result["unavailable_reason"] = "no_paired_tasks"
        return result
    if not all(_known_usage(r) for r in cost_rows):
        result["unavailable_reason"] = "unknown_usage_in_candidate_or_control"
        return result
    costs = [(sum(r["input_tokens"] + r["output_tokens"] for r in by_arch[0][key]),
              sum(r["input_tokens"] + r["output_tokens"] for r in by_arch[1][key])) for key in keys]
    numerator, denominator = sum(a for a, _ in costs), sum(b for _, b in costs)
    if not denominator:
        result["unavailable_reason"] = "zero_baseline_tokens"
        return result
    result["ratio"] = numerator / denominator
    rng, ratios = random.Random(seed), []
    for _ in range(draws):
        sample = rng.choices(costs, k=len(costs))
        base = sum(b for _, b in sample)
        if not base:
            result["undefined_bootstrap_samples"] += 1
            ratios.append(math.inf)
        else:
            ratios.append(sum(a for a, _ in sample) / base)
    ratios.sort()
    interval = [ratios[int(draws * .025)], ratios[min(draws - 1, int(draws * .975))]]
    result["ci95"] = [v if math.isfinite(v) else None for v in interval]
    return result


def _compare(rows, candidate, baseline, *, draws, seed):
    a = [r for r in rows if r["architecture"] == candidate]
    b = [r for r in rows if r["architecture"] == baseline]
    result = paired_comparison(a, b, draws=draws, seed=seed)
    result.update(candidate=candidate, baseline=baseline,
                  exact_permutation=result.get("permutation_method") == EXACT_METHOD,
                  token_ratio=_token_ratio(a, b, draws=draws, seed=seed + 107))
    return result


def analyze_confirm(rows: Iterable[dict], *, candidate, expected_tasks,
                    expected_repeats=1, draws=6000):
    """Validate the exact five-arm grid and report independent claim families.

    Pass exact planned task IDs to reject substitutions. A positive count is
    also accepted, but validates only the balanced observed-ID grid/count.
    Missing fixed fields are invalid, not inferred from a neighboring arm.
    Budget exhaustion within declared caps is a legal performance failure;
    actual overrun, unknown usage or infrastructure failure blocks all claims.
    """
    if type(expected_repeats) is not int or expected_repeats < 1:
        raise ValueError("expected_repeats must be a positive integer")
    if type(draws) is not int or draws < 100:
        raise ValueError("draws must be an integer >=100")
    planned_ids = None
    if type(expected_tasks) is int:
        if expected_tasks < 1:
            raise ValueError("expected_tasks must be positive")
        planned_count, expectation_mode = expected_tasks, "count_and_observed_balanced_grid"
    else:
        if isinstance(expected_tasks, (str, bytes)) or expected_tasks is None:
            raise ValueError("expected_tasks must be a positive count or explicit task-id iterable")
        supplied = list(expected_tasks)
        if (not supplied or any(not isinstance(t, str) or not t for t in supplied)
                or len(supplied) != len(set(supplied))):
            raise ValueError("Planned task ids must be nonempty, unique strings")
        planned_ids, planned_count, expectation_mode = set(supplied), len(supplied), "exact_planned_task_ids"
    blockers = []
    if not isinstance(candidate, str) or candidate not in CANDIDATES:
        blockers.append("unsupported_candidate")
    if candidate in CONTROLS:
        blockers.append("candidate_must_be_distinct_from_controls")
    candidate_key = candidate if isinstance(candidate, str) and candidate else "__invalid_candidate__"
    arms = tuple(dict.fromkeys((candidate_key,) + CONTROLS))
    if len(arms) != 5:
        blockers.append("required_five_arms_not_distinct")
    rows = list(rows)
    valid_rows, row_errors, seen, duplicate_cells, unexpected_cells = [], [], set(), [], []
    observed_ids, families, budgets = set(), {}, defaultdict(set)
    for index, row in enumerate(rows):
        errors = _row_errors(row, expected_repeats)
        if errors:
            row_errors.append({"row_index": index, "reasons": errors})
            continue
        task, arm, repetition = row["task_id"], row["architecture"], row["repeat"]
        observed_ids.add(task)
        cell = (task, arm, repetition)
        if arm not in arms or planned_ids is not None and task not in planned_ids:
            unexpected_cells.append(cell)
            continue
        if cell in seen:
            duplicate_cells.append(cell)
            continue
        seen.add(cell)
        if task in families and families[task] != row["family"]:
            row_errors.append({"row_index": index, "reasons": ["inconsistent_task_family"]})
        families[task] = row["family"]
        budgets[task].add(tuple(row["budget"][field] for field in ("max_calls", "max_input_tokens", "max_output_tokens")))
        valid_rows.append(row)
    task_ids = planned_ids if planned_ids is not None else observed_ids
    expected_grid = {(task, arm, rep) for task in task_ids for arm in arms for rep in range(expected_repeats)}
    missing_cells = sorted(expected_grid - seen)
    if row_errors: blockers.append("invalid_or_missing_fixed_fields")
    if duplicate_cells: blockers.append("duplicate_cells")
    if unexpected_cells: blockers.append("unexpected_cells")
    if len(task_ids) != planned_count: blockers.append("planned_task_count_mismatch")
    if missing_cells: blockers.append("missing_cells")
    if any(len(value) != 1 for value in budgets.values()): blockers.append("inconsistent_per_task_arm_budgets")
    complete = bool(not blockers and seen == expected_grid and len(rows) == len(expected_grid))
    infra = [r for r in valid_rows if r["status"] in INFRASTRUCTURE_STATUSES
             or r.get("executor_infrastructure_error") or r["evaluation"].get("executor_infrastructure_error")]
    unknown = [r for r in valid_rows if not _known_usage(r)]
    overruns = [r for r in valid_rows if _overrun(r)]
    invalidated = any(r.get("invalidated") is True for r in valid_rows)
    if not complete: blockers.append("incomplete_or_invalid_five_arm_grid")
    if infra: blockers.append("infrastructure_contamination")
    if unknown: blockers.append("unknown_usage")
    if overruns: blockers.append("actual_resource_overrun")
    if invalidated: blockers.append("study_invalidated")
    valid = complete and not infra and not unknown and not overruns and not invalidated
    primary = _compare(valid_rows, candidate_key, PRIMARY, draws=draws, seed=2026110601)
    secondary = {arm: _compare(valid_rows, candidate_key, arm, draws=draws, seed=2026110610 + i)
                 for i, arm in enumerate(SECONDARY)}
    secondary_available = all(v.get("p_two_sided") is not None for v in secondary.values())
    adjusted = holm_adjust(secondary) if secondary_available else {}

    def claim(comparison, p, alpha):
        return bool(valid and comparison["tasks"] == planned_count and comparison["exact_permutation"]
                    and comparison["delta"] is not None and comparison["delta"] > 0
                    and comparison["ci95"][0] is not None and comparison["ci95"][0] > 0
                    and p is not None and p < alpha)

    primary.update(family_alpha=ALPHA_PRIMARY, multiplicity="one_predeclared_primary_comparison",
                   confirmed_quality_improvement=claim(primary, primary.get("p_two_sided"), ALPHA_PRIMARY))
    if primary.get("p_two_sided") is not None and not primary["exact_permutation"]:
        primary["comparison_blocker"] = "exact_sign_permutation_unavailable"
    for arm, comparison in secondary.items():
        comparison.update(p_holm=adjusted.get(arm), holm_family_size=3, family_alpha=ALPHA_SECONDARY,
                          confirmed_quality_improvement=claim(comparison, adjusted.get(arm), ALPHA_SECONDARY))
        if not secondary_available:
            comparison["comparison_blocker"] = "secondary_family_has_uncomputed_comparison"
        elif not comparison["exact_permutation"]:
            comparison["comparison_blocker"] = "exact_sign_permutation_unavailable"
    by_family = {}
    for family in sorted({r["family"] for r in valid_rows}):
        sub = [r for r in valid_rows if r["family"] == family]
        by_family[family] = {
            "descriptive_only": True, "no_confirmatory_subgroup_claims": True,
            "independent_tasks": len({r["task_id"] for r in sub}),
            "summary": _summary(sub, arms),
            "unadjusted_exploratory_paired_comparisons": {
                arm: _compare(sub, candidate_key, arm, draws=draws, seed=2026110650 + i)
                for i, arm in enumerate(CONTROLS)},
        }
    return {
        "analysis_version": "v6-five-arm-quality-v1", "candidate": candidate,
        "primary_control": PRIMARY, "secondary_controls": list(SECONDARY), "required_arms": list(arms),
        "expectation_mode": expectation_mode, "expected_tasks": planned_count,
        "expected_repeats": expected_repeats, "expected_cells": planned_count * 5 * expected_repeats,
        "observed_rows": len(rows), "valid_unique_cells": len(seen), "complete": complete,
        "valid_for_confirmation": valid, "decision_blockers": sorted(set(blockers)),
        "validation": {"required_row_fields": list(REQUIRED_FIELDS), "row_errors": row_errors,
                       "missing_cell_count": len(missing_cells), "missing_cell_examples": missing_cells[:20],
                       "duplicate_cell_count": len(duplicate_cells), "duplicate_cell_examples": duplicate_cells[:20],
                       "unexpected_cell_count": len(unexpected_cells), "unexpected_cell_examples": unexpected_cells[:20]},
        "infrastructure_cells": len(infra), "unknown_usage_cells": len(unknown),
        "actual_overrun_cells": len(overruns), "invalidated": invalidated,
        "primary_comparison": primary, "secondary_comparisons_holm_family_of_three": secondary,
        "confirmed_primary_quality_improvement": primary["confirmed_quality_improvement"],
        "confirmed_secondary_quality_improvements": {arm: value["confirmed_quality_improvement"] for arm, value in secondary.items()},
        "must_win_all_controls": False,
        "summary": _summary(valid_rows, arms), "family_exploratory": by_family,
        "fwer_allocation": {"primary_single_comparison": ALPHA_PRIMARY,
                            "secondary_holm_family_of_three": ALPHA_SECONDARY, "nominal_total": .05},
        "resource_analysis": "Token ratios and paired bootstrap intervals are descriptive; no efficiency/noninferiority claim is defined.",
        "notes": ["Each declaration is separate; failure to beat every control does not erase a supported primary or secondary comparison.",
                  "All quality claims require complete five-arm data, known usage, no infrastructure contamination, no actual overrun and an exact two-sided sign permutation.",
                  "Budget exhaustion within the declared caps is a legal failed task, not automatically an invalid study.",
                  "Repeated API draws are clustered within tasks; 95% bootstrap intervals are marginal and approximate.",
                  "Count-only expected_tasks cannot detect replacing every occurrence of a planned task ID; pass exact IDs for that guarantee.",
                  "Family analyses are post hoc/exploratory and do not inherit primary or secondary confirmation."],
    }
