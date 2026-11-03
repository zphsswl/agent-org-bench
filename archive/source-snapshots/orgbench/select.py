"""Freeze exactly one development-selected candidate before holdout execution."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .run import ROOT, code_digest, digest, dump, read_rows
from .statistics import summarize


def select(dev_dir, destination):
    directory, output = ROOT / dev_dir, ROOT / destination
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["config"]["split"] != "dev":
        raise ValueError("Selection must use development data only")
    if manifest["config"]["code_hash"] != code_digest():
        raise ValueError("Code changed after development execution; restore the recorded source snapshot before selecting a confirmatory candidate")
    rows = read_rows(directory / "results.jsonl")
    expected = manifest["config"]["per_family"] * 3 * manifest["config"]["repeats"] * len(manifest["config"]["architectures"])
    if len(rows) != expected:
        raise ValueError(f"Incomplete development run: {len(rows)} != {expected}")
    summaries = summarize(rows)
    excluded = {"single", "single_refine", "hierarchy", "blackboard_no_validation"}
    candidates = [(name, summary) for name, summary in summaries.items() if name not in excluded]
    if not candidates:
        raise ValueError("No candidate architecture")
    candidates.sort(key=lambda pair: (-pair[1]["success_rate"], pair[1]["input_tokens"] + pair[1]["output_tokens"], pair[0]))
    chosen = candidates[0][0]
    result = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "development_directory": str(directory), "development_results_hash": digest(rows), "code_hash": code_digest(), "rule": "Highest dev success rate among non-baseline, non-ablation architectures; ties use total measured tokens, then lexical name", "selected": chosen, "holdout_architectures": ["single", "single_refine", "hierarchy", chosen], "ranking": [{"name": n, "success_rate": v["success_rate"], "total_tokens": v["input_tokens"] + v["output_tokens"]} for n, v in candidates]}
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous["development_results_hash"] != result["development_results_hash"] or previous["selected"] != chosen:
            raise ValueError("Frozen selection differs; use a new study instead of overwriting")
        result = previous
    else:
        dump(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", default="runs/dev01")
    parser.add_argument("--out", default="runs/selection01.json")
    args = parser.parse_args()
    select(args.dev, args.out)
