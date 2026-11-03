"""Read-only validation of a documented infrastructure-only v6 restart."""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root, dev, confirm, selection_path, amendment_path):
    """Verify provenance, not statistical validity of a possibly incomplete run."""
    root, dev, confirm = Path(root).resolve(), Path(dev), Path(confirm)
    errors = []
    try:
        selected, amendment = read(selection_path), read(amendment_path)
        parent_path = root / amendment["parent_selection_file"]
        if not parent_path.resolve().is_relative_to(root) or parent_path.is_symlink():
            raise ValueError("parent_path")
        parent = read(parent_path)
        dm, cm = read(dev / "manifest.json"), read(confirm / "manifest.json")
        dr = rows(dev / "results.jsonl")
        dc, cc = dm["config"], cm["config"]
        checks = {
            "amendment_schema": amendment["schema_version"] == "v6-infrastructure-amendment-v1",
            "no_quality_tuning": amendment["quality_based_changes"] is False and amendment["candidate_unchanged"] is True,
            "immutable_parent_manifest": amendment["original_development_manifest_modified"] is False,
            "parent_manifest": digest(dm) == amendment["parent_development_manifest_hash"],
            "parent_results": digest(dr) == amendment["parent_development_results_hash"] == selected["development_results_hash"] == parent["development_results_hash"],
            "parent_selection": digest(parent) == amendment["parent_selection_hash"] == selected["parent_selection_hash"],
            "amendment_binding": digest(amendment) == selected["amendment_hash"],
            "selection_binding": digest(selected) == cc["selection_hash"],
            "parent_protocol": sha(dev / "protocol.md") == dc["protocol_hash"] == parent["protocol_hash"] == amendment["parent_protocol_hash"],
            "parent_plan": digest(read(dev / "plan.json")) == dc["plan_hash"] == parent["plan_hash"] == amendment["parent_plan_hash"],
            "new_protocol": sha(confirm / "protocol.md") == cc["protocol_hash"] == selected["protocol_hash"] == amendment["new_protocol_hash"],
            "new_plan": digest(read(confirm / "plan.json")) == cc["plan_hash"] == selected["plan_hash"] == amendment["new_plan_hash"],
            "same_candidate": selected["candidate"] == parent["candidate"] == amendment["candidate"],
            "same_arms": selected["architectures"] == parent["architectures"] == amendment["architectures"] == cc["architectures"],
            "same_ranking": selected["ranking"] == parent["ranking"],
            "same_rule": selected["rule"] == parent["rule"],
            "same_code": selected["code_hash"] == parent["code_hash"] == amendment["code_hash"] == dc["code_hash"] == cc["code_hash"],
            "new_seed": cc["seed"] == amendment["new_confirmation_seed"] and cc["seed"] != read(root / amendment["old_confirmation_directory"] / "manifest.json")["config"]["seed"],
            "registered_size": cc["per_family"] == 20 and amendment["expected_tasks"] == 60 and amendment["expected_cells"] == 300,
            "complete_parent_development": len(dr) == 81 and read(dev / "run_state.json")["complete"] is True,
        }
        for field in ("model", "thinking", "temperature_request", "temperature_effective", "workers", "repeats", "max_calls", "max_output_tokens", "max_input_tokens", "api_base_url"):
            checks["same_setting:" + field] = dc[field] == cc[field]
        for label, directory, cfg in (("dev", dev, dc), ("holdout", confirm, cc)):
            sources = {p.name: sha(p) for p in sorted((directory / "sources/orgbench").glob("*.py"))}
            checks[label + "_snapshot"] = bool(sources) and digest(sources) == cfg["code_hash"]
        old = root / amendment["old_confirmation_directory"]
        old_rows = rows(old / "results.jsonl")
        checks["old_failure_retained"] = ((old / "INVALIDATED.md").is_file()
            and digest(old_rows) == amendment["old_confirmation_results_hash"]
            and len(old_rows) == amendment["old_confirmation_cells"]
            and sum(r["status"] == "provider_error" for r in old_rows) == amendment["old_confirmation_infrastructure_errors"])
        errors = sorted(key for key, value in checks.items() if not value)
        return {"valid": not errors, "errors": errors, "selection": selected,
                "parent_selection": parent, "amendment": amendment}
    except (KeyError, ValueError, TypeError, OSError):
        return {"valid": False, "errors": ["missing_or_malformed_recovery_lineage"]}
