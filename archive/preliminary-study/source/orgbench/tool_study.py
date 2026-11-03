"""Tool-based organization experiments: objective hidden tests, frozen selection."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
import random
import threading
import time
from pathlib import Path

from .provider import Provider, ProviderError
from .run import ROOT, code_digest, digest, dump, read_rows, build_report
from .code_tasks import generate_code_suite, evaluate_code, validate_code_public
from .tool_organizations import DESCRIPTIONS, run_tool_organization


class Transport:
    """Retry only explicit HTTP429 rejections, never ambiguous charged failures."""
    def __init__(self, provider, sleeper=time.sleep):
        self.base = provider
        self.sleeper = sleeper

    def complete(self, system, prompt, max_tokens=None):
        for attempt in range(3):
            try:
                result = self.base.complete(system, prompt, max_tokens=max_tokens)
                result["transport_attempts"] = attempt + 1
                result["prior_attempt_usage_unknown"] = attempt > 0
                return result
            except ProviderError as error:
                if error.status != 429 or attempt == 2:
                    raise
                self.sleeper((3, 10)[attempt])


def freeze_selection(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["config"]
    if config["split"] != "dev" or config["code_hash"] != code_digest():
        raise ValueError("Selection requires unchanged development implementation")
    rows = read_rows(directory / "results.jsonl")
    tasks = json.loads((directory / "tasks.public.json").read_text(encoding="utf-8"))
    expected = {(task["id"], name, rep) for task in tasks for name in config["architectures"] for rep in range(config["repeats"])}
    keys = {(r["task_id"], r["architecture"], r["repeat"]) for r in rows}
    if keys != expected or len(keys) != len(rows) or any(r["status"] in ("provider_error", "execution_error", "evaluator_error") for r in rows):
        raise ValueError("Cannot select from incomplete or infrastructure-contaminated development data")
    choices = []
    for name in config["architectures"]:
        if name in ("single_tool", "hierarchy_tool"):
            continue
        sub = [r for r in rows if r["architecture"] == name]
        choices.append({"name": name, "successes": sum(r["evaluation"]["success"] for r in sub),
                        "tokens": sum(r["input_tokens"] + r["output_tokens"] for r in sub)})
    choices.sort(key=lambda c: (-c["successes"], c["tokens"], c["name"]))
    if not choices:
        raise ValueError("No non-baseline candidate")
    selection = {"created_utc": datetime.now(timezone.utc).isoformat(), "candidate": choices[0]["name"],
                 "architectures": ["single_tool", "hierarchy_tool", choices[0]["name"]],
                 "code_hash": code_digest(), "protocol_hash": config["protocol_hash"],
                 "development_results_hash": digest(rows), "ranking": choices,
                 "rule": "Highest development full success count; ties total measured tokens then lexical name"}
    path = directory / "selection.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous["development_results_hash"] != selection["development_results_hash"]:
            raise ValueError("Cannot overwrite frozen selection")
        selection = previous
    else:
        dump(path, selection)
    print(json.dumps(selection, ensure_ascii=True, indent=2), flush=True)
    return selection


def run(args):
    directory = ROOT / args.out
    if (directory / "INVALIDATED.md").exists():
        raise ValueError("Invalidated experiment cannot be resumed as confirmation")
    if args.select_only:
        return freeze_selection(directory)
    names = args.architectures.split(",") if args.architectures else list(DESCRIPTIONS)
    selection = None
    if args.selection:
        selection = json.loads((ROOT / args.selection).read_text(encoding="utf-8"))
        if selection["code_hash"] != code_digest():
            raise ValueError("Selected implementation changed")
        names = selection["architectures"]
    if set(names) - set(DESCRIPTIONS) or len(names) != len(set(names)):
        raise ValueError("Invalid or repeated organization names")
    tasks = generate_code_suite(split=args.split, per_family=args.per_family, seed=args.seed)
    safe_tasks = [{k: v for k, v in task.items() if k != "private"} for task in tasks]
    provider = Provider.from_env(model=args.model, log_dir=directory / "api" if not args.prepare_only else None,
                                 max_output_tokens=args.max_output_tokens, timeout=240, thinking=args.thinking)
    config = {"split": args.split, "per_family": args.per_family, "seed": args.seed, "repeats": args.repeats,
              "architectures": names, "max_calls": args.max_calls, "max_output_tokens": args.max_output_tokens,
              "max_input_tokens": args.max_input_tokens, "workers": args.workers, "model": provider.model,
              "thinking": args.thinking, "temperature_request": .3,
              "temperature_effective": 1.0 if args.thinking == "enabled" else .3,
              "code_hash": code_digest(), "suite_hash": digest(tasks),
              "protocol_hash": hashlib.sha256((ROOT / args.protocol).read_bytes()).hexdigest(),
              "selection_hash": digest(selection) if selection else None,
              "transport_policy": "HTTP429 only: maximum 2 retries after 3/10 seconds; all attempts logged",
              "total_experiment_budget": "unrestricted_by_user; predefined sample size; equal per-cell limits"}
    if selection and selection.get("protocol_hash") != config["protocol_hash"]:
        raise ValueError("Selection and confirmation must use the same frozen protocol")
    path = directory / "manifest.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous["config"] != config:
            raise ValueError("Existing manifest differs; use a new experiment directory")
    else:
        dump(path, {"created_utc": datetime.now(timezone.utc).isoformat(), "client_date": "2026-11-03", "config": config})
        snapshot = directory / "sources" / "orgbench"
        snapshot.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / "orgbench").glob("*.py"):
            (snapshot / source.name).write_bytes(source.read_bytes())
        (directory / "protocol.md").write_bytes((ROOT / args.protocol).read_bytes())
    dump(directory / "tasks.private.json", tasks)
    dump(directory / "tasks.public.json", safe_tasks)
    if args.prepare_only:
        print(json.dumps({"prepared": str(directory), "tasks": len(tasks), "cells": len(tasks) * len(names) * args.repeats}), flush=True)
        return
    previous = read_rows(directory / "results.jsonl")
    done = {(r["task_id"], r["architecture"], r["repeat"]) for r in previous}
    if len(done) != len(previous):
        raise ValueError("Duplicate result cells")
    cells = [(task, name, rep) for task in tasks for name in names for rep in range(args.repeats)
             if (task["id"], name, rep) not in done]
    random.Random(args.seed + 167).shuffle(cells)
    transport = Transport(provider)
    total = len(tasks) * len(names) * args.repeats
    stop, consecutive = False, 0

    def execute(cell):
        task, name, rep = cell
        public = {k: v for k, v in task.items() if k != "private"}
        started = time.monotonic()
        try:
            outcome = run_tool_organization(name, public, transport, max_calls=args.max_calls,
                                           max_output_tokens=args.max_output_tokens, max_input_tokens=args.max_input_tokens,
                                           public_validator=validate_code_public)
        except Exception as exc:
            outcome = {"status": "execution_error", "error_type": type(exc).__name__, "answer": None,
                       "calls": 0, "input_tokens": 0, "output_tokens": 0, "usage_complete": False}
        try:
            evaluation = evaluate_code(task, outcome.get("answer"))
        except Exception as exc:
            outcome["status"] = "evaluator_error"
            evaluation = {"success": False, "score": 0., "violations": ["evaluator_error:" + type(exc).__name__]}
        if evaluation.get("executor_infrastructure_error"):
            outcome["status"] = "evaluator_error"
        if outcome.get("status") != "ok":
            outcome["best_effort_evaluation"] = evaluation
            evaluation = {"success": False, "score": 0., "violations": ["incomplete_execution:" + str(outcome.get("status"))]}
        outcome.update(task_id=task["id"], family=task["family"], architecture=name, repeat=rep,
                       evaluation=evaluation, wall_s=time.monotonic() - started,
                       finished_utc=datetime.now(timezone.utc).isoformat())
        trace = outcome.pop("trace", [])
        if any(entry.get("result", {}).get("prior_attempt_usage_unknown") for entry in trace):
            outcome["usage_complete"] = False
            outcome["transport_rejection_usage_unknown"] = True
        if any(entry.get("feedback", {}).get("validator_error") for entry in trace):
            outcome["status"] = "evaluator_error"
            outcome["evaluation"] = {"success": False, "score": 0., "violations": ["Public test tool failed"]}
        trace_path = directory / "traces" / f'{task["id"]}__{name}__r{rep}.json'
        dump(trace_path, {"task_id": task["id"], "architecture": name, "repeat": rep, "trace": trace})
        outcome["trace_file"] = str(trace_path.relative_to(directory))
        return outcome

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending, iterator = {}, iter(cells)
        def fill():
            if stop:
                return
            while len(pending) < args.workers:
                cell = next(iterator, None)
                if cell is None:
                    break
                pending[pool.submit(execute, cell)] = cell
        fill()
        with (directory / "results.jsonl").open("a", encoding="utf-8") as stream:
            while pending:
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    pending.pop(future)
                    row = future.result()
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    done.add((row["task_id"], row["architecture"], row["repeat"]))
                    infra = row["status"] in ("provider_error", "execution_error", "evaluator_error")
                    consecutive = consecutive + 1 if infra else 0
                    if consecutive >= 3:
                        stop = True
                    print(json.dumps({"progress": f"{len(done)}/{total}", "architecture": row["architecture"],
                                      "family": row["family"], "success": row["evaluation"]["success"],
                                      "score": row["evaluation"]["score"], "status": row["status"]}), flush=True)
                fill()
    dump(directory / "provider_accounting.json", provider.totals)
    dump(directory / "run_state.json", {"complete": len(done) == total, "executed_cells": len(done),
                                       "expected_cells": total, "infrastructure_circuit_latched": stop})
    build_report(directory)
    if selection:
        from .decision import analyze_confirm
        rows = read_rows(directory / "results.jsonl")
        decision = analyze_confirm(rows, candidate=selection["candidate"], expected_tasks=[t["id"] for t in tasks])
        dump(directory / "decision.json", decision)
    print(json.dumps({"finished_cells": len(done), "expected_cells": total, "complete": len(done) == total,
                      "provider_accounting": provider.totals, "directory": str(directory)}, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--split", default="dev", choices=("dev", "holdout"))
    parser.add_argument("--per-family", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026110301)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--architectures", default="")
    parser.add_argument("--selection", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--thinking", default="disabled", choices=("enabled", "disabled"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--max-input-tokens", type=int, default=32000)
    parser.add_argument("--protocol", default="docs/protocol_v4.md")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--select-only", action="store_true")
    args = parser.parse_args()
    if min(args.per_family, args.repeats, args.workers, args.max_calls, args.max_output_tokens, args.max_input_tokens) < 1:
        parser.error("Counts and per-cell limits must be positive")
    run(args)


if __name__ == "__main__":
    main()
