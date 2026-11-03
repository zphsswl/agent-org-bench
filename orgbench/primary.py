"""Predeclared v2 primary comparisons, separate from exploratory comparisons."""
import argparse
import json
from .run import ROOT, read_rows, dump, digest
from .statistics import summarize, paired_comparison, holm_adjust


def analyze(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rows = read_rows(directory / "results.jsonl")
    config = manifest["config"]
    names = {"single", "single_refine", "hierarchy", "adaptive", "artifact_single", "artifact_contracts", "contract_adaptive"}
    fixed = {"seed": 20261104, "thinking": "enabled", "split": "holdout", "per_family": 10,
             "repeats": 2, "max_calls": 5, "max_output_tokens": 12000, "max_input_tokens": 24000,
             "workers": 24, "input_run_cap": 4000000, "output_run_cap": 5200000,
             "timeout_per_call_s": 240, "model": "deepseek-v4-pro"}
    if set(config["architectures"]) != names or any(config.get(k) != v for k, v in fixed.items()):
        raise ValueError("Not the predeclared v2 confirmatory configuration")
    expected = config["per_family"] * 3 * config["repeats"] * len(names)
    public = json.loads((directory / "tasks.public.json").read_text(encoding="utf-8"))
    expected_keys = {(t["id"], arch, rep) for t in public for arch in names for rep in range(2)}
    actual_keys = {(r["task_id"], r["architecture"], r["repeat"]) for r in rows}
    complete = len(rows) == expected == len(expected_keys) and actual_keys == expected_keys
    infrastructure_errors = sum(r.get("status") in ("provider_error", "execution_error", "evaluator_error") or not r.get("usage_complete", True) for r in rows)
    invalidated = (directory / "INVALIDATED.md").exists()
    valid_for_confirmation = complete and infrastructure_errors == 0 and not invalidated
    summaries = summarize(rows)
    candidate = [r for r in rows if r["architecture"] == "contract_adaptive"]
    comparisons = {base: paired_comparison(candidate, [r for r in rows if r["architecture"] == base]) for base in ("artifact_single", "single_refine", "hierarchy")}
    adjusted = holm_adjust(comparisons)
    for base, values in comparisons.items():
        values["p_holm"] = adjusted.get(base)
        values["confirmed_quality_improvement"] = bool(valid_for_confirmation and values["tasks"] == 30 and values["delta"] > 0 and values["ci95"][0] > 0 and values["p_holm"] <= .05)
        a, b = summaries.get("contract_adaptive"), summaries.get(base)
        values["total_token_ratio"] = ((a["input_tokens"] + a["output_tokens"]) / max(1, b["input_tokens"] + b["output_tokens"])) if a and b else None
    data = {"complete": complete, "valid_for_confirmation": valid_for_confirmation, "infrastructure_errors": infrastructure_errors, "invalidated": invalidated, "executed": len(rows), "expected": expected, "results_hash": digest(rows), "protocol_hash": config["protocol_hash"], "architectures": summaries, "primary_comparisons_holm_family_of_three": comparisons, "ci_note": "95% paired task bootstrap intervals are marginal, not simultaneous; p-values use Holm across exactly the three predeclared primary comparisons."}
    dump(directory / "primary.json", data)
    lines = ["# 第二轮：预注册主要比较", "", f"运行完整：{complete}；{len(rows)}/{expected}。可用于确认：{valid_for_confirmation}；基础设施错误：{infrastructure_errors}；已作废标记：{invalidated}。同一 DeepSeek 模型，统一思考模式，每题相同资源上限。", "", "| 相对对照（契约组织减对照） | 成功率差 | 95%配对区间 | Holm p | 总Token比 | 确认质量提升 |", "|---|---:|---|---:|---:|---|"]
    for base, value in comparisons.items():
        if value["delta"] is None:
            lines.append(f'| {base} | 数据不足 | — | — | — | False |')
            continue
        lo, hi = value["ci95"]
        lines.append(f'| {base} | {value["delta"]:+.1%} | [{lo:+.1%}, {hi:+.1%}] | {value["p_holm"]:.5f} | {value["total_token_ratio"]:.2f}x | {value["confirmed_quality_improvement"]} |')
    lines += ["", "候选为contract_adaptive。区间按独立题聚类，两次重复不当独立样本。区间未经同时校正；三项p做Holm校正。新组织相对共享全部程序支撑的artifact_single才反映分工与合并的增量；相对其他旧对照是组织和任务专用程序的联合效果。即使质量提高，也须单独评估实际资源代价。未完成不能宣称确认胜出。", "", "详细各组与任务族指标见同目录report.md。"]
    (directory / "primary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="runs/holdout03_recovery")
    args = parser.parse_args()
    analyze(ROOT / args.run)
