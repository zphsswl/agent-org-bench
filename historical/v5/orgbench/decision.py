"""Frozen-candidate decisions for the tool study; no API or file side effects.

Two claim families split nominal FWER .05: quality superiority gets .025 (Holm over
two baselines); baseline efficiency gets .025 through an intersection-union
rule. Efficiency means 5pp conservative noninferiority plus >15% total-token
saving, not exact equality of quality or strict population Pareto dominance.

The caller must select its candidate on development data before confirmation.
Task clusters, not stochastic repetitions, are the independent sampling units.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import math
from numbers import Real
import random
import statistics

from .statistics import holm_adjust, paired_comparison


INFRASTRUCTURE_STATUSES = frozenset({"provider_error", "execution_error", "evaluator_error"})
QUALITY_FAMILY_ALPHA = .025
EFFICIENCY_FAMILY_ALPHA = .025
LOSS_MARGIN = .05
TOKEN_RATIO_THRESHOLD = .85
MIN_USABLE_SUCCESS_RATE = .5


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    """Stable log-sum-exp CDF, including large n and boundary probabilities."""
    if k < 0:
        return 0.
    if k >= n or probability <= 0:
        return 1.
    if probability >= 1:
        return 0.
    log_p, log_q = math.log(probability), math.log1p(-probability)
    terms = [math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
             + j * log_p + (n - j) * log_q for j in range(k + 1)]
    largest = max(terms)
    return min(1., math.exp(largest) * math.fsum(math.exp(t - largest) for t in terms))


def clopper_pearson_upper(losses: int, tasks: int, alpha: float = .025) -> float:
    """One-sided (1-alpha) exact binomial upper bound; no tasks -> 1.

    In particular, 0/n is never treated as a known zero population loss rate.
    The binomial model assumes independent task clusters from the declared
    target task population; repeated API samples are not additional clusters.
    """
    if type(losses) is not int or type(tasks) is not int or not 0 <= losses <= tasks:
        raise ValueError("Require integer 0 <= losses <= tasks")
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie strictly between zero and one")
    if not tasks or losses == tasks:
        return 1.
    if losses == 0:
        return -math.expm1(math.log(alpha) / tasks)
    low, high = losses / tasks, 1.
    for _ in range(80):
        middle = (low + high) / 2
        if _binomial_cdf(losses, tasks, middle) > alpha:
            low = middle
        else:
            high = middle
    return high


def _finite_nonnegative(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _known_usage(row: dict) -> bool:
    return (row.get("usage_complete", True) is not False
            and not row.get("accounting_unknown", False)
            and not row.get("usage_unknown", False)
            and all(_finite_nonnegative(row.get(k)) for k in ("input_tokens", "output_tokens")))


def _token_interval(candidate_tasks: dict, baseline_tasks: dict, keys: list,
                    *, draws: int, seed: int) -> dict:
    if not keys:
        return {"tasks": 0, "ratio": None, "ci95": [None, None],
                "upper_one_sided_97_5": None, "undefined_bootstrap_samples": 0}
    costs = [(sum(r["input_tokens"] + r["output_tokens"] for r in candidate_tasks[k]),
              sum(r["input_tokens"] + r["output_tokens"] for r in baseline_tasks[k]))
             for k in keys]
    numerator = sum(a for a, _ in costs)
    denominator = sum(b for _, b in costs)
    rng = random.Random(seed)
    ratios = []
    undefined = 0
    for _ in range(draws):
        sample = rng.choices(costs, k=len(costs))
        base = sum(b for _, b in sample)
        if base <= 0:
            undefined += 1
            ratios.append(math.inf)
        else:
            ratios.append(sum(a for a, _ in sample) / base)
    ratios.sort()
    lo = ratios[int(draws * .025)]
    hi = ratios[min(draws - 1, int(draws * .975))]
    finite = lambda value: value if math.isfinite(value) else None
    return {"tasks": len(keys), "ratio": numerator / denominator if denominator > 0 else None,
            "ci95": [finite(lo), finite(hi)], "upper_one_sided_97_5": finite(hi),
            "undefined_bootstrap_samples": undefined,
            "method": "paired_task_cluster_bootstrap_ratio_of_total_tokens",
            "cost_metric": "input_tokens_plus_output_tokens_not_currency"}


def analyze_confirm(rows: Iterable[dict], candidate: str, baseline: str = "single_tool",
                    secondary: str = "hierarchy_tool", *,
                    expected_tasks: int | Iterable[str] | None = None,
                    expected_repeats: int = 1, invalidated: bool = False,
                    bootstrap_draws: int = 6000, seed: int = 20261103) -> dict:
    """Return descriptive results and guarded, predeclared claim decisions.

    expected_tasks may be a positive planned count or exact task-id iterable.
    Without it, completeness cannot be established and claims are disabled.
    A count validates a balanced observed task grid; exact ids are preferable
    when the driver has them. Additional architectures are descriptive only.
    """
    if any(not isinstance(s, str) or not s for s in (candidate, baseline, secondary)):
        raise ValueError("Architecture names must be nonempty strings")
    if len({candidate, baseline, secondary}) != 3:
        raise ValueError("Candidate and the two baselines must be distinct")
    if type(expected_repeats) is not int or expected_repeats < 1:
        raise ValueError("expected_repeats must be a positive integer")
    if type(bootstrap_draws) is not int or bootstrap_draws < 100:
        raise ValueError("bootstrap_draws must be an integer >= 100")
    planned_ids = None
    planned_count = None
    if expected_tasks is not None:
        if type(expected_tasks) is int:
            if expected_tasks < 1:
                raise ValueError("expected_tasks must be positive")
            planned_count = expected_tasks
        elif isinstance(expected_tasks, (str, bytes)):
            raise ValueError("Pass task ids as an iterable, not a single string")
        else:
            supplied = list(expected_tasks)
            if not supplied or len(set(supplied)) != len(supplied):
                raise ValueError("Expected task ids must be nonempty and unique")
            planned_ids = set(supplied)
            planned_count = len(planned_ids)

    rows = list(rows)
    required = (candidate, baseline, secondary)
    grouped = {name: defaultdict(list) for name in required}
    seen, observed_ids, validation_errors = set(), set(), []
    families = {}
    relevant = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            validation_errors.append(f"row_{index}:not_an_object")
            continue
        if row.get("architecture") not in required:
            continue
        relevant.append(row)
        task_id, repetition = row.get("task_id"), row.get("repeat")
        success = row.get("evaluation", {}).get("success") if isinstance(row.get("evaluation"), dict) else None
        if (not isinstance(task_id, str) or not task_id or type(repetition) is not int
                or repetition not in range(expected_repeats)
                or not isinstance(success, (bool, int, float)) or success not in (False, True)
                or not isinstance(row.get("status"), str) or not row["status"]
                or not isinstance(row.get("family"), str) or not row["family"]):
            validation_errors.append(f"row_{index}:invalid_cell_or_success")
            continue
        if success and row["status"] not in ("ok", "success"):
            validation_errors.append(f"row_{index}:success_on_incomplete_execution")
        key = (task_id, row["architecture"], repetition)
        if key in seen:
            validation_errors.append(f"row_{index}:duplicate_cell")
            continue
        seen.add(key)
        observed_ids.add(task_id)
        if task_id in families and families[task_id] != row.get("family"):
            validation_errors.append(f"row_{index}:inconsistent_task_family")
        families[task_id] = row.get("family")
        grouped[row["architecture"]][task_id].append(row)
    task_ids = planned_ids if planned_ids is not None else observed_ids
    expected_grid = {(t, name, rep) for t in task_ids for name in required
                     for rep in range(expected_repeats)}
    complete = bool(planned_count is not None and len(task_ids) == planned_count
                    and seen == expected_grid and not validation_errors)
    infra = [row for row in relevant if row.get("status") in INFRASTRUCTURE_STATUSES]
    invalidated = bool(invalidated or any(row.get("invalidated", False) for row in relevant))
    valid = complete and not infra and not invalidated
    reasons = list(validation_errors)
    if planned_count is None:
        reasons.append("planned_task_count_or_ids_not_provided")
    if not complete:
        reasons.append("incomplete_or_unbalanced_confirmation_grid")
    if infra:
        reasons.append("infrastructure_contamination")
    if invalidated:
        reasons.append("study_invalidated")

    quality = {}
    for index, name in enumerate((baseline, secondary)):
        a = [row for vals in grouped[candidate].values() for row in vals]
        b = [row for vals in grouped[name].values() for row in vals]
        quality[name] = paired_comparison(a, b, draws=bootstrap_draws, seed=seed + index)
    adjusted = holm_adjust(quality)
    for name, result in quality.items():
        result["p_holm"] = adjusted.get(name)
        result["holm_family_size"] = 2
        result["family_alpha"] = QUALITY_FAMILY_ALPHA
        result["confirmed_quality_improvement"] = bool(
            valid and result["tasks"] == planned_count and result["delta"] is not None
            and result["delta"] > 0 and result["ci95"][0] > 0
            and result["p_holm"] is not None and result["p_holm"] < QUALITY_FAMILY_ALPHA)

    keys = sorted(grouped[candidate].keys() & grouped[baseline].keys())
    losses = sum(statistics.mean(float(r["evaluation"]["success"]) for r in grouped[candidate][key])
                 < statistics.mean(float(r["evaluation"]["success"]) for r in grouped[baseline][key])
                 for key in keys)
    loss_upper = clopper_pearson_upper(losses, len(keys), alpha=EFFICIENCY_FAMILY_ALPHA)
    cost_rows = [row for name in (candidate, baseline)
                 for vals in grouped[name].values() for row in vals]
    usage_complete = bool(cost_rows) and all(_known_usage(row) for row in cost_rows)
    token = (_token_interval(grouped[candidate], grouped[baseline], keys,
                            draws=bootstrap_draws, seed=seed + 77)
             if usage_complete else {"tasks": len(keys), "ratio": None, "ci95": [None, None],
                                     "upper_one_sided_97_5": None,
                                     "method": "not_computed_unknown_usage"})
    noninferior = bool(valid and keys and loss_upper <= LOSS_MARGIN)
    cheaper = bool(valid and usage_complete and token["upper_one_sided_97_5"] is not None
                   and token["upper_one_sided_97_5"] < TOKEN_RATIO_THRESHOLD)
    candidate_rate = (statistics.mean(statistics.mean(float(r["evaluation"]["success"])
                                                     for r in grouped[candidate][key]) for key in keys)
                      if keys else None)
    baseline_rate = (statistics.mean(statistics.mean(float(r["evaluation"]["success"])
                                                    for r in grouped[baseline][key]) for key in keys)
                     if keys else None)
    usable = bool(valid and candidate_rate is not None and baseline_rate is not None
                  and candidate_rate >= MIN_USABLE_SUCCESS_RATE
                  and baseline_rate >= MIN_USABLE_SUCCESS_RATE)
    efficiency = {
        "baseline": baseline, "tasks": len(keys), "loss_tasks": losses,
        "loss_rate": losses / len(keys) if keys else None,
        "loss_probability_upper_one_sided_97_5": loss_upper,
        "loss_bound_method": "exact_clopper_pearson_binomial_task_loss_indicator",
        "quality_loss_margin": LOSS_MARGIN,
        "loss_bound_interpretation": "P(task_mean_candidate_success < task_mean_baseline_success) conservatively bounds mean success loss; it is not a bound on exact equality",
        "quality_noninferiority_passed": noninferior,
        "usage_complete": usage_complete, "tokens": token,
        "token_ratio_upper_threshold": TOKEN_RATIO_THRESHOLD,
        "token_saving_passed": cheaper, "family_alpha": EFFICIENCY_FAMILY_ALPHA,
        "candidate_observed_success_rate": candidate_rate,
        "baseline_observed_success_rate": baseline_rate,
        "usability_min_success_rate": MIN_USABLE_SUCCESS_RATE,
        "usability_gate_passed": usable,
        "confirmed_efficiency_improvement": bool(noninferior and cheaper and usable),
        "claim_scope": "Both observed success rates >=50%, 5pp conservative noninferiority and >15% total-token saving; not strict Pareto or exact quality equivalence",
    }
    if not usage_complete:
        reasons.append("efficiency_usage_incomplete")

    observed = {}
    by_arch = defaultdict(list)
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("evaluation"), dict):
            by_arch[row.get("architecture", "unknown")].append(row)
    for name, values in sorted(by_arch.items()):
        by_task = defaultdict(list)
        for row in values:
            if row["evaluation"].get("success") in (False, True):
                by_task[row.get("task_id")].append(row)
        if not by_task:
            continue
        known = all(_known_usage(row) for row in values)
        observed[name] = {
            "tasks": len(by_task), "cells": len(values),
            "success_rate": statistics.mean(statistics.mean(float(r["evaluation"]["success"])
                                                            for r in vals) for vals in by_task.values()),
            "mean_tokens": (statistics.mean(statistics.mean(r["input_tokens"] + r["output_tokens"]
                                                            for r in vals) for vals in by_task.values())
                            if known else None),
            "usage_complete": known,
        }
    for name, point in observed.items():
        point["on_observed_pareto_frontier"] = bool(point["mean_tokens"] is not None and not any(
            other["mean_tokens"] is not None and other["success_rate"] >= point["success_rate"]
            and other["mean_tokens"] <= point["mean_tokens"]
            and (other["success_rate"] > point["success_rate"] or other["mean_tokens"] < point["mean_tokens"])
            for other_name, other in observed.items() if other_name != name))
    return {
        "candidate": candidate, "baseline": baseline, "secondary": secondary,
        "complete": complete, "valid_for_confirmation": valid,
        "invalidated": invalidated, "infrastructure_errors": len(infra),
        "expected_tasks": planned_count, "expected_repeats": expected_repeats,
        "observed_required_cells": len(seen), "expected_required_cells": len(expected_grid),
        "decision_blockers": reasons,
        "quality_comparisons_holm_family_of_two": quality,
        "efficiency": efficiency,
        "confirmed_quality_improvement_vs_all_baselines": all(r["confirmed_quality_improvement"] for r in quality.values()),
        "confirmed_efficiency_improvement": efficiency["confirmed_efficiency_improvement"],
        "observed_pareto": {"descriptive_only": True, "architectures": observed,
                            "note": "Observed points and frontier are not population confirmation or noninferiority tests."},
        "fwer_allocation": {"total": .05, "quality_holm_two": .025, "efficiency_intersection_union": .025},
        "assumptions": ["Candidate selected only on development data before this confirmation.",
                        "Independent task clusters; exact binomial model for task loss probability.",
                        "95% task-paired bootstrap intervals are marginal; total-token cost is not currency.",
                        "FWER allocation is nominal; bootstrap coverage is approximate, not an exact finite-sample guarantee.",
                        "Repeated samples do not increase the independent task count."],
    }
