"""Task-clustered statistics: stochastic repetitions are not independent tasks."""
from collections import defaultdict, Counter
from fractions import Fraction
import math
import random
import statistics


def task_means(rows, metric="success"):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["task_id"]].append(float(row["evaluation"][metric]))
    return {key: statistics.mean(vals) for key, vals in grouped.items()}


def cluster_interval(rows, metric="success", draws=4000, seed=8831):
    values = list(task_means(rows, metric).values())
    if not values:
        return [None, None]
    rng = random.Random(seed)
    estimates = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return [estimates[int(draws * .025)], estimates[min(draws - 1, int(draws * .975))]]


def paired_comparison(candidate, baseline, draws=6000, seed=7343):
    a, b = task_means(candidate), task_means(baseline)
    keys = sorted(a.keys() & b.keys())
    if not keys:
        return {"tasks": 0, "delta": None, "ci95": [None, None], "p_two_sided": None}
    diffs = [a[k] - b[k] for k in keys]
    rng = random.Random(seed)
    estimates = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(draws))
    fractions = []
    for key in keys:
        av = [int(row["evaluation"]["success"]) for row in candidate if row["task_id"] == key]
        bv = [int(row["evaluation"]["success"]) for row in baseline if row["task_id"] == key]
        fractions.append(Fraction(sum(av), len(av)) - Fraction(sum(bv), len(bv)))
    denominator = math.lcm(*(value.denominator for value in fractions))
    weights = [int(value * denominator) for value in fractions if value]
    observed = abs(sum(weights))
    # Integer-scaled dynamic programming counts every sign assignment exactly.
    if sum(map(abs, weights)) <= 200000 and len(weights) <= 200:
        distribution = Counter({0: 1})
        for weight in weights:
            updated = Counter()
            for total, count in distribution.items():
                updated[total + weight] += count
                updated[total - weight] += count
            distribution = updated
        extreme = sum(count for total, count in distribution.items() if abs(total) >= observed)
        p = extreme / (1 << len(weights))
        method = "exact_integer_dp_task_sign_permutation"
    else:
        extreme = sum(abs(sum(v * rng.choice((-1, 1)) for v in weights)) >= observed for _ in range(draws))
        p = (extreme + 1) / (draws + 1)
        method = "monte_carlo_task_sign_permutation"
    return {"tasks": len(keys), "delta": statistics.mean(diffs), "ci95": [estimates[int(draws * .025)], estimates[int(draws * .975)]], "p_two_sided": p, "permutation_method": method}


def holm_adjust(comparisons):
    ordered = sorted(((k, v["p_two_sided"]) for k, v in comparisons.items() if v["p_two_sided"] is not None), key=lambda x: x[1])
    adjusted, running = {}, 0.0
    for i, (key, p) in enumerate(ordered):
        running = max(running, min(1., (len(ordered) - i) * p))
        adjusted[key] = running
    return adjusted


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["architecture"]].append(row)
    out = {}
    for name, vals in sorted(groups.items()):
        times = sorted(v.get("wall_s", 0.) for v in vals)
        successes = sum(v["evaluation"]["success"] for v in vals)
        tokens = sum(v.get("input_tokens", 0) + v.get("output_tokens", 0) for v in vals)
        out[name] = {
            "cells": len(vals), "tasks": len(task_means(vals)),
            "successes": successes, "success_rate": successes / len(vals),
            "ci95_task_cluster": cluster_interval(vals),
            "ci95_hoeffding_conservative": [max(0., successes / len(vals) - math.sqrt(math.log(40) / (2 * len(task_means(vals))))), min(1., successes / len(vals) + math.sqrt(math.log(40) / (2 * len(task_means(vals)))))],
            "mean_score": statistics.mean(v["evaluation"]["score"] for v in vals),
            "input_tokens": sum(v.get("input_tokens", 0) for v in vals),
            "output_tokens": sum(v.get("output_tokens", 0) for v in vals),
            "calls": sum(v.get("calls", 0) for v in vals),
            "tokens_per_success": tokens / successes if successes else None,
            "mean_wall_s": statistics.mean(times),
            "p95_wall_s": times[max(0, math.ceil(len(times) * .95) - 1)],
            "errors": sum(v.get("status") not in ("ok", "success") for v in vals),
            "families": {f: {"cells": len(sub := [v for v in vals if v["family"] == f]), "success_rate": statistics.mean(v["evaluation"]["success"] for v in sub), "mean_score": statistics.mean(v["evaluation"]["score"] for v in sub)} for f in sorted({v["family"] for v in vals})},
        }
    return out
