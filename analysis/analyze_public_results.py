"""Recompute published main-study quality statistics from metrics only; no API calls.

This verifies arithmetic on released outcomes, not the original grading or
archive validity. Those depend on the archived protocol and validation receipt.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orgbench.statistics import paired_comparison, holm_adjust


def analyze(directory):
    rows = [json.loads(line) for line in (directory / "holdout_cells.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    candidate = json.loads((directory / "state.json").read_text(encoding="utf-8"))["frozen_candidate"]
    controls = ("single_self_review", "single_tool", "hierarchy_tool", "best_of_three")
    arms = [candidate, *controls]
    tasks = {row["task_id"] for row in rows}
    cells = {(row["task_id"], row["architecture"], row["repeat"]) for row in rows}
    if len(rows) != 300 or len(cells) != 300 or len(tasks) != 60 or cells != {(task, arm, 0) for task in tasks for arm in arms}:
        raise ValueError("Expected the exact released 60-task five-arm grid")
    grouped = {arm: [r for r in rows if r["architecture"] == arm] for arm in arms}
    primary = paired_comparison(grouped[candidate], grouped[controls[0]], seed=2026110601)
    secondary = {arm: paired_comparison(grouped[candidate], grouped[arm], seed=2026110610 + index)
                 for index, arm in enumerate(controls[1:])}
    for arm, p in holm_adjust(secondary).items():
        secondary[arm]["p_holm"] = p
    def passes(comparison, key):
        return comparison[key] < .025 and comparison["delta"] > 0 and comparison["ci95"][0] > 0
    return {"metric_replay_only": True, "candidate": candidate,
            "summary": {arm: {"successes": sum(r["evaluation"]["success"] for r in sub), "tasks": len(sub),
                              "mean_input_plus_output_tokens": sum(r["input_tokens"] + r["output_tokens"] for r in sub) / len(sub)}
                        for arm, sub in grouped.items()},
            "primary": primary, "secondary": secondary,
            "primary_quality_gate": passes(primary, "p_two_sided"),
            "secondary_quality_gates": {arm: passes(value, "p_holm") for arm, value in secondary.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results/main")
    args = parser.parse_args()
    print(json.dumps(analyze(args.results), indent=2))
