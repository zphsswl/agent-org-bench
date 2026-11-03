"""Render figures from released main-study metrics and archived statistics only.

No model/API requests, private cases, candidate answers or traces are used.
Statistics are read from decision.json, not newly tested. Run from a repository
checkout with matplotlib installed; after copying this script into analysis/ the
default repository is that checkout's root.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEV_ORDER = ("plain_single", "single_tool", "single_self_review", "hierarchy_tool",
             "best_of_three", "bazaar_tool", "contract_team", "adaptive_tools", "evidence_gated")
ARMS = ("single_tool", "single_self_review", "hierarchy_tool", "best_of_three", "adaptive_tools")
FAMILIES = ("code_versions", "code_ledger", "code_config")
BAR_ORDER = ("single_self_review", "adaptive_tools", "best_of_three", "single_tool", "hierarchy_tool")
LABELS = {
    "single_tool": "Single agent\n+ tools",
    "single_self_review": "Single-agent\nself-review",
    "hierarchy_tool": "Hierarchical\nteam",
    "best_of_three": "Best of\nthree",
    "adaptive_tools": "Adaptive\nrouter",
}
FAMILY_LABELS = {"code_versions": "Version conflict\nmerge", "code_ledger": "Stateful\nledger",
                 "code_config": "Conditional\nconfiguration"}


def read_public(repository):
    directory = repository / "results/main"
    rows = [json.loads(line) for line in (directory / "holdout_cells.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    decision = json.loads((directory / "decision.json").read_text(encoding="utf-8"))
    task_family, seen = {}, set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("task_id"), str)
                or row.get("family") not in FAMILIES or row.get("architecture") not in ARMS
                or type(row.get("repeat")) is not int or row["repeat"] != 0
                or row.get("usage_complete") is not True
                or type(row.get("evaluation", {}).get("success")) is not bool):
            raise ValueError("Invalid released metric cell")
        task, family, arm = row["task_id"], row["family"], row["architecture"]
        key = task, arm, row["repeat"]
        if key in seen or task in task_family and task_family[task] != family:
            raise ValueError("Duplicate or inconsistent released cell")
        seen.add(key)
        task_family[task] = family
    if (len(rows) != 300 or len(task_family) != 60
            or seen != {(task, arm, 0) for task in task_family for arm in ARMS}
            or Counter(task_family.values()) != Counter({family: 20 for family in FAMILIES})
            or decision.get("valid_for_confirmation") is not True
            or decision.get("complete") is not True or decision.get("expected_tasks") != 60
            or decision.get("candidate") != "adaptive_tools"):
        raise ValueError("Expected the validated 60-task, five-arm released confirmation")
    counts = {arm: sum(row["evaluation"]["success"] for row in rows if row["architecture"] == arm) for arm in ARMS}
    cells = {family: {arm: sum(row["evaluation"]["success"] for row in rows
                              if row["architecture"] == arm and row["family"] == family)
                      for arm in ARMS} for family in FAMILIES}
    for arm in ARMS:
        if decision["summary"][arm]["successes"] != counts[arm] or decision["summary"][arm]["tasks"] != 60:
            raise ValueError("Released metrics disagree with archived overall statistics")
    for family in FAMILIES:
        for arm in ARMS:
            if decision["family_exploratory"][family]["summary"][arm]["successes"] != cells[family][arm]:
                raise ValueError("Released metrics disagree with archived family statistics")
    return rows, decision, counts, cells


def make_figures(repository):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    repository = Path(repository).resolve()
    confirmation_rows, decision, counts, cells = read_public(repository)
    output = repository / "results/main"
    palette = {arm: plt.get_cmap("tab10")(DEV_ORDER.index(arm)) for arm in DEV_ORDER}
    style = {"font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 17,
             "axes.labelsize": 12, "axes.spines.top": False, "axes.spines.right": False,
             "figure.facecolor": "white", "savefig.facecolor": "white"}

    def save(fig, name):
        path = output / name
        fig.savefig(path, dpi=240, bbox_inches="tight", metadata={"Description": "Released confirmation metrics; no private data or new statistical tests."})
        plt.close(fig)
        return {"file": path.relative_to(repository).as_posix(), "bytes": path.stat().st_size}

    generated = []
    with plt.rc_context(style):
        fig, ax = plt.subplots(figsize=(10.6, 6.2))
        positions = list(range(len(BAR_ORDER)))
        rates = [counts[arm] / 60 for arm in BAR_ORDER]
        ax.bar(positions, rates, color=[palette[arm] for arm in BAR_ORDER], width=.66,
               edgecolor="white", linewidth=1.0, zorder=3)
        for index, arm in enumerate(BAR_ORDER):
            ax.text(index, rates[index] + .025, f"{counts[arm]}/60\n{rates[index]:.1%}",
                    ha="center", va="bottom", fontsize=12, fontweight="semibold")
        ax.set_xticks(positions, [LABELS[arm] for arm in BAR_ORDER])
        ax.set_ylim(0, 1.03)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_ylabel("Successful delivery under declared resource limits")
        ax.set_title("Confirmation task success", loc="left", pad=30, fontweight="semibold")
        ax.text(0, 1.035, "Same 60 tasks per strategy | 300 complete paired cells", transform=ax.transAxes,
                fontsize=11, color="#555555", va="bottom")
        ax.grid(axis="y", color="#d8dde3", alpha=.7, zorder=0)
        ax.set_axisbelow(True)
        fig.subplots_adjust(left=.12, right=.98, top=.80, bottom=.21)
        fig.text(.12, .035, "Observed rates. No preregistered superiority comparison for the adaptive router passed.\n"
                 "Formal paired comparisons and archived intervals appear in paired_quality_deltas.png.",
                 fontsize=9.5, color="#555555", va="bottom")
        generated.append(save(fig, "confirmation_success.png"))

        fig, ax = plt.subplots(figsize=(11.2, 5.5))
        rates = [[cells[family][arm] / 20 for arm in ARMS] for family in FAMILIES]
        heat = ax.imshow(rates, vmin=0, vmax=1, cmap="Blues", aspect="auto")
        ax.set_xticks(range(len(ARMS)), [LABELS[arm] for arm in ARMS])
        ax.set_yticks(range(len(FAMILIES)), [FAMILY_LABELS[family] for family in FAMILIES])
        for tick, arm in zip(ax.get_xticklabels(), ARMS):
            tick.set_color(palette[arm]); tick.set_fontweight("semibold")
        for row_index, family in enumerate(FAMILIES):
            for column, arm in enumerate(ARMS):
                value = cells[family][arm]
                ax.text(column, row_index, f"{value}/20\n{value / 20:.0%}", ha="center", va="center",
                        fontsize=13, color="white" if value / 20 >= .65 else "#162c43")
        ax.set_xticks([i - .5 for i in range(len(ARMS) + 1)], minor=True)
        ax.set_yticks([i - .5 for i in range(len(FAMILIES) + 1)], minor=True)
        ax.grid(which="minor", color="white", linewidth=2)
        ax.tick_params(which="both", length=0)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.set_title("Task-family success — exploratory", loc="left", pad=34, fontweight="semibold")
        ax.text(0, 1.065, "20 tasks per cell; subgroup winners are not confirmed", transform=ax.transAxes,
                color="#555555", fontsize=11, va="bottom")
        colorbar = fig.colorbar(heat, ax=ax, fraction=.035, pad=.025)
        colorbar.set_label("Observed task success")
        colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1))
        fig.subplots_adjust(left=.17, right=.94, top=.77, bottom=.23)
        fig.text(.17, .035, "Cell shading encodes success rate; column labels use the strategy palette.\n"
                 "These family slices are descriptive and do not establish task-specific superiority.",
                 fontsize=9.5, color="#555555", va="bottom")
        generated.append(save(fig, "task_family_heatmap.png"))

        primary = decision["primary_comparison"]
        controls = ("single_self_review", "single_tool", "hierarchy_tool", "best_of_three")
        comparisons = [primary] + [decision["secondary_comparisons_holm_family_of_three"][arm] for arm in controls[1:]]
        for control, comparison in zip(controls, comparisons):
            if comparison.get("baseline") != control or comparison.get("tasks") != 60:
                raise ValueError("Archived comparison identity mismatch")
            numbers = [comparison["delta"], *comparison["ci95"], comparison["p_two_sided"]]
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in numbers):
                raise ValueError("Archived comparison has missing/nonfinite values")
        fig, (ax, details) = plt.subplots(1, 2, figsize=(13.0, 5.5),
                                        gridspec_kw={"width_ratios": (2.9, 2.25)})
        positions = list(reversed(range(len(controls))))
        span = max(abs(bound * 100) for comparison in comparisons for bound in comparison["ci95"])
        limit = math.ceil((span + 4) / 5) * 5
        for control, comparison, position in zip(controls, comparisons, positions):
            low, high = [value * 100 for value in comparison["ci95"]]
            delta = comparison["delta"] * 100
            ax.plot([low, high], [position, position], color=palette[control], linewidth=3)
            ax.plot([low, low], [position - .075, position + .075], color=palette[control], linewidth=1.4)
            ax.plot([high, high], [position - .075, position + .075], color=palette[control], linewidth=1.4)
            ax.scatter(delta, position, s=85, color=palette[control], marker="D" if control == controls[0] else "o", zorder=4)
            if control == controls[0]:
                p_text = f"raw p = {comparison['p_two_sided']:.3f}  (primary)"
            else:
                p_text = f"Holm p = {comparison['p_holm']:.3f}  (secondary, m=3)"
            details.text(.03, position + .12, f"{delta:+.1f}  [{low:+.1f}, {high:+.1f}] pp",
                         fontsize=11.5, va="center")
            details.text(.03, position - .15, p_text, fontsize=10, color="#555555", va="center")
        ax.axvline(0, color="#444444", linestyle="--", linewidth=1.2, zorder=1)
        ax.set_xlim(-limit, limit)
        ax.set_ylim(-.6, len(controls) - .4)
        details.set_ylim(ax.get_ylim()); details.set_xlim(0, 1); details.set_axis_off()
        labels = [LABELS[arm].replace("\n", " ") + (" (primary)" if i == 0 else "") for i, arm in enumerate(controls)]
        ax.set_yticks(positions, labels)
        ax.tick_params(axis="y", length=0, pad=10)
        ax.set_xlabel("Adaptive router − control (percentage points)", labelpad=12)
        ax.grid(axis="x", color="#d8dde3", alpha=.7)
        ax.spines["left"].set_visible(False)
        fig.suptitle("Paired quality differences: adaptive router vs controls", x=.23, ha="left",
                     y=.97, fontsize=17, fontweight="semibold")
        fig.text(.23, .885, "Archived estimates, same 60 paired tasks; colors identify the compared control", fontsize=10.5, color="#555555")
        details.text(.03, 1.06, "Difference [marginal 95% interval] / reported p", transform=details.transAxes,
                     fontsize=10.5, fontweight="semibold")
        fig.subplots_adjust(left=.23, right=.98, top=.78, bottom=.23, wspace=.08)
        fig.text(.23, .035, "Intervals are marginal 95% paired task-bootstrap intervals, not simultaneous intervals.\n"
                 "Primary uses its archived raw p; secondary p-values use the archived three-comparison Holm adjustment.\n"
                 "Values below zero favor the control. No new tests or subgroup claims are introduced.",
                 fontsize=9.2, color="#555555", va="bottom")
        generated.append(save(fig, "paired_quality_deltas.png"))

        development_rows = [json.loads(line) for line in (output / "dev_cells.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        development_tasks = {row["task_id"] for row in development_rows}
        grid = {(row["task_id"], row["architecture"], row["repeat"]) for row in development_rows}
        if (len(development_rows) != 81 or len(development_tasks) != 9
                or grid != {(task, arm, 0) for task in development_tasks for arm in DEV_ORDER}):
            raise ValueError("Expected the released nine-task, nine-policy development grid")
        fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))
        for ax, rows, order, title in (
                (axes[0], development_rows, DEV_ORDER, "Development: 9 tasks per policy"),
                (axes[1], confirmation_rows, ARMS, "Confirmation: 60 tasks per policy")):
            for arm in order:
                group = [row for row in rows if row["architecture"] == arm]
                x = sum(row["input_tokens"] + row["output_tokens"] for row in group) / len(group)
                y = sum(row["evaluation"]["success"] for row in group) / len(group)
                primary = arm == "single_self_review"
                ax.scatter(x, y, s=100 if primary else 62, marker="D" if primary else "o", color=palette[arm], zorder=3)
                offset = (-105, 11) if arm in ("adaptive_tools", "hierarchy_tool") else (9, -22) if arm == "best_of_three" else (9, 10)
                if arm == "hierarchy_tool":
                    offset = (-35, 14)
                if primary:
                    offset = (9, -22) if ax is axes[0] else (-112, 12)
                ax.annotate(arm, (x, y), xytext=offset, textcoords="offset points", fontsize=8.3)
            ax.set_title(title, loc="left", fontsize=13)
            ax.set_xlabel("Observed mean input + output tokens / task", fontsize=10)
            ax.set_ylabel("Successful delivery rate", fontsize=10)
            ax.set_ylim(-.03, 1.1)
            ax.margins(x=.19)
            ax.grid(color="#d8dde3", alpha=.65)
            ax.set_axisbelow(True)
            ax.yaxis.set_major_formatter(PercentFormatter(1))
        fig.suptitle("Observed quality and resource use", x=.07, ha="left", fontsize=18, fontweight="semibold")
        fig.text(.07, .02, "Descriptive, separate development and confirmation cohorts. Equal ceilings do not imply equal actual compute.", fontsize=9, color="#555555")
        fig.subplots_adjust(left=.07, right=.985, bottom=.18, top=.83, wspace=.27)
        generated.append(save(fig, "quality_tokens.png"))
    return {"source": "released confirmation metrics and archived decision", "new_statistical_tests": False,
            "tasks_per_strategy": 60, "successes": counts, "figures": generated}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(make_figures(args.repository), indent=2))


if __name__ == "__main__":
    main()
