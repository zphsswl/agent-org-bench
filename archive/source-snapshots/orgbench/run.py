"""CLI experiments, resumable append-only records and frozen run manifests."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import time
import urllib.parse

from .architectures import ARCHITECTURES, run_architecture
from .provider import Provider
from .tasks import generate_suite, evaluate, validate_public
from .statistics import summarize, paired_comparison, holm_adjust

ROOT = Path(__file__).resolve().parent.parent


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def code_digest():
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "orgbench").glob("*.py"))})


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_rows(path):
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Corrupt or interrupted JSONL at {path}, line {number}. Original data preserved; inspect its matching trace/API logs before repairing.") from exc
    return rows


def build_report(directory):
    rows = read_rows(directory / "results.jsonl")
    summary = summarize(rows)
    comparisons = {}
    for name in summary:
        for base in ("single", "single_refine", "hierarchy"):
            if name != base and base in summary:
                comparisons[f"{name} vs {base}"] = paired_comparison([r for r in rows if r["architecture"] == name], [r for r in rows if r["architecture"] == base])
    adjusted = holm_adjust(comparisons)
    for key, p in adjusted.items():
        comparisons[key]["p_holm"] = p
    data = {"architectures": summary, "comparisons": comparisons, "cells": len(rows), "note": "Task-cluster bootstrap; repeat ids are NOT provider random seeds; all executed comparisons Holm adjusted. Exploratory dev results are not confirmatory."}
    dump(directory / "summary.json", data)
    lines = ["# 实验结果（自动生成）", "", "成功由隐藏答案和确定性程序判断，并要求组织完整执行且预算内结束；实际消耗并不相等。相同的是每题资源上限。重复编号不是供应商随机种子。", "", "下表为经验Bootstrap区间：全对/全错时会退化，绝不表示总体成功概率确定。summary.json另附按独立题数的保守Hoeffding区间。", "", "| 组织 | 成功/运行 | 成功率 | 按任务聚类的95%区间 | 均分 | 输入/输出Token | 调用 | 平均/P95秒 |", "|---|---:|---:|---|---:|---:|---:|---:|"]
    for name, s in sorted(summary.items(), key=lambda item: (-item[1]["success_rate"], item[1]["input_tokens"] + item[1]["output_tokens"])):
        lo, hi = s["ci95_task_cluster"]
        lines.append(f'| {name} | {s["successes"]}/{s["cells"]} | {s["success_rate"]:.1%} | [{lo:.1%}, {hi:.1%}] | {s["mean_score"]:.3f} | {s["input_tokens"]:,}/{s["output_tokens"]:,} | {s["calls"]} | {s["mean_wall_s"]:.1f}/{s["p95_wall_s"]:.1f} |')
    lines += ["", "## 分任务族", "", "| 组织 | 任务族 | 运行 | 成功率 | 均分 |", "|---|---|---:|---:|---:|"]
    for name, s in summary.items():
        for family, f in s["families"].items():
            lines.append(f'| {name} | {family} | {f["cells"]} | {f["success_rate"]:.1%} | {f["mean_score"]:.3f} |')
    lines += ["", "## 配对比较", "", "同一任务的重复先取平均，再对任务配对比较；所有列出的检验统一做 Holm 多重比较校正。小样本区间只反映这套合成任务的抽样，不支持普遍最优结论。", "", "| 比较 | 独立题目数 | 成功率差 | 95%区间 | 校正p |", "|---|---:|---:|---|---:|"]
    for key, s in comparisons.items():
        if not s["tasks"]:
            continue
        lo, hi = s["ci95"]
        lines.append(f'| {key} | {s["tasks"]} | {s["delta"]:+.1%} | [{lo:+.1%}, {hi:+.1%}] | {s["p_holm"]:.4f} |')
    lines += ["", "## 资源说明", "", "Token 为供应商返回的已知计量，包含缓存命中输入；若调用失败且usage未知，数值仅为下界，见provider_accounting.json。本实现cell内独立分支串行调用，不支持并行架构时延优势的结论；延迟还受cell间并发、服务负载和网络影响。coordination_tokens 只计显式标记的管理调用输出（包含最终merge），不精确代表所有通信开销。未开展故障/错误注入，故不报告错误传播率或故障恢复率。"]
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def run(args):
    directory = ROOT / args.out
    directory.mkdir(parents=True, exist_ok=True)
    names = args.architectures.split(",") if args.architectures else list(ARCHITECTURES)
    unknown = set(names) - set(ARCHITECTURES)
    if unknown:
        raise ValueError(f"Unknown architectures: {unknown}")
    tasks = generate_suite(split=args.split, per_family=args.per_family, seed=args.seed)
    # Freeze private evaluation data on disk, never send it to the execution function.
    public = [{k: v for k, v in task.items() if k != "private"} for task in tasks]
    resolved_model = re.sub(r"\[[^\]]+\]$", "", (args.model or os.getenv("ANTHROPIC_MODEL") or os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "")).strip())
    endpoint = urllib.parse.urlsplit(os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))
    config = {"split": args.split, "per_family": args.per_family, "seed": args.seed, "repeats": args.repeats, "architectures": names, "max_calls": args.max_calls, "max_output_tokens": args.max_output_tokens, "max_input_tokens": args.max_input_tokens, "model": resolved_model, "endpoint_host": endpoint.hostname, "endpoint_path": endpoint.path, "temperature": 0.3, "thinking": "disabled", "workers": args.workers, "input_run_cap": args.input_run_cap, "output_run_cap": args.output_run_cap, "suite_hash": digest(tasks), "code_hash": code_digest()}
    protocol_path = ROOT / args.protocol
    config["thinking"] = args.thinking
    config["temperature_effective"] = 1.0 if args.thinking == "enabled" and resolved_model.startswith("deepseek") else 0.3
    config["timeout_per_call_s"] = 240
    config["protocol_hash"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["config"] != config:
            raise ValueError("Existing run configuration/code differs; use a new --out directory.")
    else:
        dump(manifest_path, {"created_at_utc": datetime.now(timezone.utc).isoformat(), "config": config, "reproducibility": "task generation seeded; API sampling not seeded; repeat ids denote independent calls; no response reuse across architectures"})
        snapshot = directory / "sources" / "orgbench"
        snapshot.mkdir(parents=True, exist_ok=True)
        for module in (ROOT / "orgbench").glob("*.py"):
            (snapshot / module.name).write_bytes(module.read_bytes())
        (directory / "protocol.md").write_bytes(protocol_path.read_bytes())
    dump(directory / "tasks.private.json", tasks)
    dump(directory / "tasks.public.json", public)
    if args.prepare_only:
        print(json.dumps({"prepared": str(directory), "tasks": len(tasks), "cells": len(tasks) * len(names) * args.repeats}), flush=True)
        return
    provider = Provider.from_env(model=resolved_model, log_dir=directory / "api", max_output_tokens=args.max_output_tokens, timeout=240, thinking=args.thinking)
    done_rows = read_rows(directory / "results.jsonl")
    completed = {(r["task_id"], r["architecture"], r["repeat"]) for r in done_rows}
    cells = [(task, name, rep) for task in tasks for name in names for rep in range(args.repeats) if (task["id"], name, rep) not in completed]
    random.Random(args.seed + 773).shuffle(cells)
    total = len(completed) + len(cells)
    inputs = sum(r.get("input_tokens", 0) for r in done_rows)
    outputs = sum(r.get("output_tokens", 0) for r in done_rows)
    errors = 0
    stop_dispatch = False

    def execute(cell):
        task, name, rep = cell
        started = time.monotonic()
        safe_task = {k: v for k, v in task.items() if k != "private"}
        try:
            outcome = run_architecture(name, safe_task, provider, max_calls=args.max_calls, max_output_tokens=args.max_output_tokens, max_input_tokens=args.max_input_tokens, public_validator=validate_public)
        except Exception as exc:
            outcome = {"status": "execution_error", "answer": None, "error": type(exc).__name__, "calls": 0, "input_tokens": 0, "output_tokens": 0, "usage_complete": False, "accounting_unknown": True, "trace": []}
        answer = outcome.get("answer")
        try:
            evaluation = evaluate(task, answer) if isinstance(answer, dict) else {"success": False, "score": 0., "violations": ["No valid JSON answer"]}
        except Exception as exc:
            evaluation = {"success": False, "score": 0., "violations": ["Evaluator error: " + type(exc).__name__]}
            outcome["status"] = "evaluator_error"
        if outcome.get("status") not in ("ok", "success"):
            outcome["best_effort_evaluation"] = evaluation
            evaluation = {"success": False, "score": 0., "violations": ["Organization did not finish within its declared budget: " + str(outcome.get("status"))]}
        outcome.update({"task_id": task["id"], "family": task["family"], "architecture": name, "repeat": rep, "evaluation": evaluation, "wall_s": time.monotonic() - started, "finished_utc": datetime.now(timezone.utc).isoformat()})
        trace = outcome.pop("trace", [])
        trace_path = directory / "traces" / f'{task["id"]}__{name}__r{rep}.json'
        dump(trace_path, {"task_id": task["id"], "architecture": name, "repeat": rep, "trace": trace})
        outcome["trace_file"] = str(trace_path.relative_to(directory))
        return outcome

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        it = iter(cells)
        def refill():
            if stop_dispatch or inputs >= args.input_run_cap or outputs >= args.output_run_cap:
                return
            while len(pending) < args.workers:
                cell = next(it, None)
                if cell is None:
                    break
                pending[pool.submit(execute, cell)] = cell
        refill()
        with (directory / "results.jsonl").open("a", encoding="utf-8") as stream:
            while pending:
                ready, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in ready:
                    pending.pop(future)
                    row = future.result()
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    completed.add((row["task_id"], row["architecture"], row["repeat"]))
                    inputs += row.get("input_tokens", 0)
                    outputs += row.get("output_tokens", 0)
                    errors = errors + 1 if row.get("status") in ("provider_error", "execution_error", "evaluator_error") else 0
                    if errors >= 5:
                        stop_dispatch = True
                    print(json.dumps({"progress": f"{len(completed)}/{total}", "architecture": row["architecture"], "family": row["family"], "success": row["evaluation"]["success"], "status": row.get("status"), "tokens_total": inputs + outputs}), flush=True)
                refill()
    data = build_report(directory)
    dump(directory / "provider_accounting.json", provider.totals)
    dump(directory / "run_state.json", {"complete": data["cells"] == total,
         "executed_cells": data["cells"], "expected_cells": total,
         "infrastructure_circuit_latched": stop_dispatch,
         "global_input_cap_reached": inputs >= args.input_run_cap,
         "global_output_cap_reached": outputs >= args.output_run_cap})
    print(json.dumps({"finished_cells": data["cells"], "expected_cells": total, "run_complete": data["cells"] == total, "input_tokens": inputs, "output_tokens": outputs, "report": str(directory / "report.md")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="runs/dev01")
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--per-family", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--architectures", default="")
    parser.add_argument("--model", default=None)
    parser.add_argument("--thinking", choices=["enabled", "disabled"], default="disabled")
    parser.add_argument("--protocol", default="docs/protocol.md")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--max-output-tokens", type=int, default=3600)
    parser.add_argument("--max-input-tokens", type=int, default=24000)
    parser.add_argument("--input-run-cap", type=int, default=4000000)
    parser.add_argument("--output-run-cap", type=int, default=500000)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if min(args.per_family, args.repeats, args.workers, args.max_calls, args.max_input_tokens, args.max_output_tokens) <= 0:
        parser.error("counts and budgets must be positive")
    run(args)


if __name__ == "__main__":
    main()
