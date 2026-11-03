"""Task-specialized artifact contracts; no hidden evaluator is imported.

This is a mechanism prototype for orgbench's three declared task types, not a
general autonomous organization. Its added deterministic tools are shared with
the artifact_single control. Planning ranks *submitted feasible* solutions by
their public objective; neither branch coverage nor a self-report proves that a
worker searched its branch exhaustively.
"""
from __future__ import annotations

import copy
import json
import time
from typing import Any, Callable

from orgbench.architectures import _Run, _BudgetStop
from orgbench.tasks import validate_public, _planning_value


DESCRIPTIONS = {
    "artifact_contracts": "Typed public artifacts, deterministic task-specific decomposition, feasibility gates and deterministic merge.",
    "artifact_single": "Single-agent control sharing the exact public normalization, decomposition hints and feasibility/objective tools.",
}

SCOPE = ("Task-type-specialized mechanism prototype for orgbench evidence, planning and sequential tasks; "
         "not a general autonomous organization and not an exhaustive optimizer.")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _public_task(task: dict) -> dict:
    # Explicit allowlist before deepcopy: even a hidden value with side-effectful
    # serialization/deepcopy is never touched.
    return copy.deepcopy({key: task[key] for key in
                          ("id", "family", "prompt", "schema", "public", "metadata") if key in task})


def _rules(task: dict) -> str:
    # The prototype deliberately relies on the benchmark's declared format.
    return task["prompt"].split("\n\nINPUT:", 1)[0]


def _chunks(values: list, count: int = 3) -> list[list]:
    if not values:
        return [[]]
    count = min(count, len(values))
    return [values[i * len(values) // count:(i + 1) * len(values) // count] for i in range(count)]


def _repack(task: dict, public: dict, schema: dict | None = None, *, extra_rules: str = "") -> dict:
    schema = copy.deepcopy(task.get("schema", {})) if schema is None else schema
    result = {"id": task.get("id"), "family": task["family"], "public": public,
              "schema": schema, "metadata": copy.deepcopy(task.get("metadata", {}))}
    result["prompt"] = (_rules(task) + "\n" + extra_rules + "\n\nINPUT:\n" + _dump(public)
                        + "\n\nReturn one JSON object matching: " + _dump(schema))
    return result


def _normalize_events(public: dict) -> tuple[dict, dict]:
    """Remove globally cancelled IDs and later duplicates; do no ledger replay."""
    events = public["events"]
    revoked = {event["target"] for event in events if event["op"] == "cancel"}
    seen, normalized, duplicates = set(), [], []
    for index, event in enumerate(events):
        if event["op"] == "cancel" or event["id"] in revoked:
            continue
        if event["id"] in seen:
            duplicates.append({"id": event["id"], "input_index": index})
            continue
        seen.add(event["id"])
        normalized.append(copy.deepcopy(event))
    result = {"initial_balances": copy.deepcopy(public["initial_balances"]),
              "initial_frozen": copy.deepcopy(public["initial_frozen"]),
              "events": normalized}
    audit = {"rule": "global_cancel_then_first_occurrence_only_no_state_execution",
             "revoked_ids": sorted(revoked), "later_duplicates_removed": duplicates,
             "input_event_count": len(events), "kept_event_ids": [e["id"] for e in normalized],
             "computed_ledger_state": False}
    return result, audit


def prepare_public_artifacts(task: dict) -> dict:
    """Expose exactly the preprocessing available to BOTH experimental systems."""
    safe = _public_task(task)
    family, public = safe["family"], safe["public"]
    normalization = None
    if family == "evidence":
        contracts = []
        for index, keys in enumerate(_chunks(public["requested"])):
            records = [copy.deepcopy(row) for row in public["records"] if row["key"] in keys]
            record_ids = {row["id"] for row in records}
            shard_public = {"requested": list(keys), "records": records,
                            "revocations": [copy.deepcopy(r) for r in public["revocations"]
                                            if r["target"] in record_ids],
                            "authority": copy.deepcopy(public["authority"]), "cutoff": public["cutoff"]}
            schema = {"facts": {key: copy.deepcopy(safe["schema"]["facts"][key]) for key in keys}}
            contracts.append({"id": f"facts-{index + 1}", "keys": keys,
                              "task": _repack(safe, shard_public, schema),
                              "input_scope": "only records/revocations for assigned keys; all authority/cutoff rules"})
        prepared = safe
    elif family == "sequential":
        normalized, normalization = _normalize_events(public)
        extra = ("This INPUT is deterministically normalized: all global cancellation targets and all "
                 "later duplicates have ALREADY been removed. Every listed id is unique and non-revoked. "
                 "Replay the events in the listed order; cancellation/duplicate preprocessing must not "
                 "discard another event. Do not recompute a hidden answer.")
        prepared = _repack(safe, normalized, extra_rules=extra)
        contracts = [{"id": f"state-{index + 1}", "events": events,
                      "event_ids": [event["id"] for event in events],
                      "requires": "previous typed state: balances, frozen, cumulative accepted",
                      "provides": "next typed state: balances, frozen, cumulative accepted"}
                     for index, events in enumerate(_chunks(normalized["events"]))]
    elif family == "planning":
        roots = [project["id"] for project in public["projects"] if not project["requires"]]
        if len(roots) < 2:
            raise ValueError("Planning prototype requires at least two prerequisite-free projects")
        anchors = roots[:2]
        contracts = []
        for first in (False, True):
            for second in (False, True):
                bits = list(zip(anchors, (first, second)))
                contracts.append({"id": f"search-{int(first)}{int(second)}",
                                  "must_include": [pid for pid, selected in bits if selected],
                                  "must_exclude": [pid for pid, selected in bits if not selected],
                                  "requires": "complete original project constraints",
                                  "provides": "one complete feasible candidate within this fixed-bit subspace"})
        prepared = safe
    else:
        raise ValueError("Unsupported task family for artifact prototype: " + str(family))
    return {"task": prepared, "contracts": contracts, "normalization": normalization,
            "scope": SCOPE, "uses_hidden_answers": False}


def _validate(validator: Callable, task: dict, answer: dict | None) -> list[str]:
    if answer is None:
        return ["Answer is not a parseable JSON object"]
    try:
        return list(validator(task, answer))
    except Exception as exc:
        return ["Public validator unavailable: " + type(exc).__name__]


def _gate(run: _Run, task: dict, answer: dict | None, contract: dict,
          validator: Callable, *, accepted_before: int | None = None) -> list[str]:
    checked = answer
    if accepted_before is not None and isinstance(answer, dict):
        checked = copy.deepcopy(answer)
        if type(checked.get("accepted")) is int:
            checked["accepted"] -= accepted_before
    issues = _validate(validator, task, checked)
    if task["family"] == "planning" and isinstance(answer, dict):
        selected = answer.get("selected")
        if isinstance(selected, list) and all(isinstance(pid, str) for pid in selected):
            chosen = set(selected)
            if not set(contract["must_include"]).issubset(chosen):
                issues.append("candidate omits a fixed included anchor")
            if chosen.intersection(contract["must_exclude"]):
                issues.append("candidate selects a fixed excluded anchor")
    run.trace.append({"event": "artifact_feasibility_gate", "contract": contract["id"],
                      "violations": issues, "passed": not issues,
                      "accepted_before": accepted_before, "uses_hidden_score": False})
    return issues


def _repair_prompt(task: dict, contract: dict, raw: str, issues: list[str]) -> str:
    return (task["prompt"] + "\nTyped artifact contract: " + _dump({k: v for k, v in contract.items() if k != "task"})
            + "\nPrevious artifact: " + raw + "\nPUBLIC format/feasibility violations: " + _dump(issues)
            + "\nRepair this assigned artifact. Recheck the public rules; no correctness oracle is available. "
              "Return the required JSON object. Compact structured checks may be included.")


def _evidence(run: _Run, prepared: dict, validator: Callable) -> dict:
    contracts = prepared["contracts"]
    artifacts = []
    # First issue all independent tasks. No shard sees another shard's output.
    for index, contract in enumerate(contracts):
        task = contract["task"]
        raw, answer = run.call(
            "typed evidence shard worker " + contract["id"],
            task["prompt"] + "\nContract: return facts for EXACTLY these keys: " + _dump(contract["keys"])
            + ". Each fact must retain value AND source. Optional compact structured checks are allowed.",
            remaining_stages=len(contracts) - index + max(0, run.max_calls - len(contracts)),
        )
        issues = _gate(run, task, answer, contract, validator)
        artifacts.append({"contract": contract, "raw": raw, "answer": answer, "issues": issues})
    for artifact in artifacts:
        while artifact["issues"] and run.calls < run.max_calls and run.output_tokens < run.output_cap:
            raw, answer = run.call(
                "typed evidence local repair " + artifact["contract"]["id"],
                _repair_prompt(artifact["contract"]["task"], artifact["contract"],
                               artifact["raw"], artifact["issues"]),
                remaining_stages=1,
            )
            artifact.update(raw=raw, answer=answer,
                            issues=_gate(run, artifact["contract"]["task"], answer,
                                         artifact["contract"], validator))
    facts = {}
    failed = []
    for artifact in artifacts:
        if artifact["issues"]:
            failed.append(artifact["contract"]["id"])
            continue
        # Gates guarantee exactly the assigned, disjoint key set. The merge
        # retains each entire fact payload, rather than dropping its provenance.
        for key in artifact["contract"]["keys"]:
            facts[key] = copy.deepcopy(artifact["answer"]["facts"][key])
    answer = {"facts": facts}
    final_issues = _validate(validator, prepared["task"], answer)
    run.trace.append({"event": "deterministic_artifact_merge", "policy": "disjoint_key_union_preserve_value_and_source",
                      "merged_keys": list(facts), "failed_contracts": failed,
                      "public_violations": final_issues, "llm_manager_calls": 0})
    if failed or final_issues:
        run.status = "contract_failure"
    return answer


def _state_task(prepared: dict, contract: dict, state: dict) -> dict:
    public = {"initial_balances": copy.deepcopy(state["balances"]),
              "initial_frozen": copy.deepcopy(state["frozen"]), "events": contract["events"]}
    extra = ("NORMALIZED SEGMENT CONTRACT: The events below are globally non-revoked and have unique ids. "
             "initial_balances and initial_frozen are the incoming state for THIS segment. "
             f"The incoming cumulative accepted count is {state['accepted']}. "
             "Return accepted as that incoming count PLUS the number of events executed in THIS segment. "
             "Do not replay earlier segments. Return all balances, the full frozen set and cumulative accepted. "
             "Optional compact structured checks may be included.")
    return _repack(prepared["task"], public, extra_rules=extra)


def _sequential(run: _Run, prepared: dict, validator: Callable) -> dict | None:
    public = prepared["task"]["public"]
    state = {"balances": copy.deepcopy(public["initial_balances"]),
             "frozen": copy.deepcopy(public["initial_frozen"]), "accepted": 0}
    contracts = prepared["contracts"]
    for index, contract in enumerate(contracts):
        task = _state_task(prepared, contract, state)
        run.trace.append({"event": "typed_state_handoff", "contract": contract["id"],
                          "incoming_state": copy.deepcopy(state), "event_ids": contract["event_ids"]})
        raw, answer = run.call(
            "typed sequential segment executor " + contract["id"], task["prompt"],
            remaining_stages=len(contracts) - index + max(0, run.max_calls - len(contracts)),
        )
        issues = _gate(run, task, answer, contract, validator, accepted_before=state["accepted"])
        remaining_required = len(contracts) - index - 1
        while (issues and run.calls + remaining_required < run.max_calls
               and run.output_tokens < run.output_cap):
            raw, answer = run.call(
                "typed sequential local repair " + contract["id"],
                _repair_prompt(task, contract, raw, issues),
                remaining_stages=remaining_required + 1,
            )
            issues = _gate(run, task, answer, contract, validator, accepted_before=state["accepted"])
        if issues:
            run.status = "contract_failure"
            run.trace.append({"event": "state_chain_stopped", "contract": contract["id"],
                              "reason": "invalid typed state cannot feed the next segment"})
            return None
        state = {"balances": copy.deepcopy(answer["balances"]),
                 "frozen": copy.deepcopy(answer["frozen"]), "accepted": answer["accepted"]}
    run.trace.append({"event": "deterministic_artifact_merge", "policy": "last_valid_typed_state",
                      "segments": len(contracts), "llm_manager_calls": 0})
    return state


def _loose_utility(public: dict, answer: dict | None) -> int:
    if not isinstance(answer, dict) or not isinstance(answer.get("selected"), list):
        return -1
    selected = answer["selected"]
    if any(not isinstance(pid, str) for pid in selected):
        return -1
    known = {project["id"] for project in public["projects"]}
    if not set(selected).issubset(known):
        return -1
    return _planning_value(public, selected)


def _planning(run: _Run, prepared: dict, validator: Callable) -> dict | None:
    task, contracts = prepared["task"], prepared["contracts"]
    artifacts = []
    for index, contract in enumerate(contracts):
        prompt = (task["prompt"] + "\nYou own ONE fixed-bit search subspace. All other workers are independent. "
                  "Mandatory included project ids: " + _dump(contract["must_include"])
                  + ". Mandatory excluded project ids: " + _dump(contract["must_exclude"])
                  + ". Find the highest-utility feasible candidate you can within this subspace. "
                    "Return a COMPLETE selected list. If you found no feasible candidate, return "
                    '{"selected":[],"no_feasible_candidate":true}; this is not a proof. '
                    "Compact structured checks may be included.")
        raw, answer = run.call("typed partition search worker " + contract["id"], prompt,
                               remaining_stages=len(contracts) - index + max(0, run.max_calls - len(contracts)))
        issues = _gate(run, task, answer, contract, validator)
        utility = _loose_utility(task["public"], answer)
        artifacts.append({"contract": contract, "raw": raw, "answer": answer,
                          "issues": issues, "utility": utility})
        run.trace.append({"event": "public_candidate_utility", "contract": contract["id"],
                          "utility": utility, "feasible_in_contract": not issues,
                          "computed_from_public_objective_only": True, "is_optimality_oracle": False})
    invalid = [artifact for artifact in artifacts if artifact["issues"]]
    if invalid and run.calls < run.max_calls and run.output_tokens < run.output_cap:
        # A heuristic chooses one promising invalid proposal for a repair lease.
        # Its utility is not interpreted as a valid solution's value until gated.
        artifact = sorted(invalid, key=lambda a: (-a["utility"], len(a["issues"]), a["contract"]["id"]))[0]
        raw, answer = run.call(
            "typed partition feasibility repair " + artifact["contract"]["id"],
            _repair_prompt(task, artifact["contract"], artifact["raw"], artifact["issues"])
            + "\nIts ungated public utility was " + str(artifact["utility"])
            + ". A higher utility never overrides feasibility or fixed-bit requirements.",
        )
        artifact.update(raw=raw, answer=answer,
                        issues=_gate(run, task, answer, artifact["contract"], validator),
                        utility=_loose_utility(task["public"], answer))
    feasible = [artifact for artifact in artifacts if not artifact["issues"]]
    winner = (sorted(feasible, key=lambda a: (-a["utility"], a["contract"]["id"]))[0]
              if feasible else None)
    run.trace.append({"event": "deterministic_artifact_merge", "policy": "max_public_utility_among_contract_feasible_candidates",
                      "feasible_contracts": [a["contract"]["id"] for a in feasible],
                      "selected_contract": winner["contract"]["id"] if winner else None,
                      "selected_public_utility": winner["utility"] if winner else None,
                      "llm_manager_calls": 0, "exhaustive_optimality_claim": False})
    if winner is None:
        run.status = "contract_failure"
        return None
    return {"selected": list(winner["answer"]["selected"])}


def _contract_summary(prepared: dict) -> list[dict]:
    return [{key: value for key, value in contract.items() if key not in ("task", "events")}
            for contract in prepared["contracts"]]


def _single(run: _Run, prepared: dict, validator: Callable) -> dict | None:
    task = prepared["task"]
    hints = _contract_summary(prepared)
    public_prompt = task["prompt"]
    if task["family"] == "evidence":
        grouped = {"authority": task["public"]["authority"], "cutoff": task["public"]["cutoff"],
                   "shards": [{key: value for key, value in c["task"]["public"].items()
                               if key not in ("authority", "cutoff")} for c in prepared["contracts"]]}
        public_prompt = (_rules(task) + "\nThe same source data has been deterministically grouped into shards. "
                         "Apply the shared authority/cutoff rules to every shard and return ALL requested keys."
                         + "\n\nINPUT:\n" + _dump(grouped)
                         + "\nReturn one complete answer matching: " + _dump(task["schema"]))
    prompt = (public_prompt + "\nYou are ONE solver with access to the same deterministic preprocessing "
              "and decomposition hints as the artifact organization. You own ALL components: " + _dump(hints)
              + "\nFor planning, the four fixed-bit cases partition the full space; you may search any or all cases. "
                "For evidence, solve every shard then combine all requested keys. For sequential replay, "
                "the events are already globally normalized; you may internally use the suggested segment boundaries. "
                "Return ONE complete final answer object. Compact structured checks may be included.")
    best = None
    best_utility = -1
    previous = None
    rounds = run.max_calls
    for index in range(rounds):
        current_prompt = prompt
        if previous is not None:
            current_prompt += "\nYour preceding candidate and PUBLIC feedback: " + _dump(previous)
            current_prompt += "\nRecompute carefully, correct feasibility issues and improve utility if applicable."
        if best is not None:
            current_prompt += "\nIncumbent feasible candidate: " + _dump(best)
            if task["family"] == "planning":
                current_prompt += "\nIncumbent PUBLIC utility: " + str(best_utility)
        try:
            raw, answer = run.call("same single artifact-aware solver, iteration " + str(index + 1),
                                   current_prompt, remaining_stages=1)
        except _BudgetStop:
            if best is not None and run.status in ("budget_exhausted", "input_budget_exhausted"):
                run.trace.append({"event": "optional_refinement_stopped_with_complete_incumbent",
                                  "reason": run.status, "actual_budget_exceeded": False})
                run.status = "ok"
                return best
            raise
        issues = _validate(validator, task, answer)
        utility = _loose_utility(task["public"], answer) if task["family"] == "planning" else None
        run.trace.append({"event": "single_public_feasibility_and_objective_feedback", "iteration": index + 1,
                          "violations": issues, "public_utility": utility,
                          "is_optimality_oracle": False})
        if not issues:
            if task["family"] != "planning" or utility > best_utility:
                best = copy.deepcopy(answer)
                best_utility = utility if utility is not None else -1
        previous = {"candidate": answer, "raw": raw, "public_violations": issues}
        if task["family"] == "planning":
            previous["public_utility"] = utility
    run.trace.append({"event": "deterministic_single_incumbent_selection",
                      "policy": "best_public_utility_feasible" if task["family"] == "planning" else "last_public_feasible",
                      "llm_manager_calls": 0})
    if best is None:
        run.status = "contract_failure"
    return best


def _finish(name: str, run: _Run, answer: dict | None, started: float) -> dict:
    if run.status == "ok" and answer is None:
        run.status = "invalid_json"
    return {
        "architecture": name, "effective_architecture": name, "answer": answer,
        "trace": run.trace, "calls": run.calls, "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens, "cache_read_input_tokens": run.cache_read,
        "estimated_input_tokens": run.estimated_input_tokens,
        "wall_s": time.perf_counter() - started, "status": run.status, "error": run.error,
        "coordination_tokens": run.coordination_tokens,
        "coordination_metric": "administrative_call_output_tokens_only",
        "budget": {"max_calls": run.max_calls, "max_output_tokens": run.output_cap,
                   "max_input_tokens": run.input_cap,
                   "input_enforcement": "conservative_preflight_estimate_plus_observed_usage",
                   "input_is_exact_hard_cap": False},
        "actual_input_budget_exceeded": run.input_tokens > run.input_cap,
        "actual_output_budget_exceeded": run.output_tokens > run.output_cap,
        "usage_complete": not any(row.get("usage_unknown") for row in run.trace),
        "mechanism_scope": SCOPE, "uses_hidden_answers": False,
        "shared_preprocessing_control": "artifact_single",
    }


def _execute(name: str, task: dict, provider: Any, *, max_calls: int = 5,
             max_output_tokens: int = 3600, max_input_tokens: int = 24000,
             public_validator: Callable | None = None) -> dict:
    if min(max_calls, max_output_tokens, max_input_tokens) < 1:
        raise ValueError("All run budgets must be positive")
    started = time.perf_counter()
    safe = _public_task(task)
    validator = public_validator or validate_public
    prepared = prepare_public_artifacts(safe)
    run = _Run(safe, provider, max_calls, max_output_tokens, max_input_tokens, validator)
    run.trace.append({"event": "deterministic_artifact_plan", "family": safe["family"],
                      "contracts": _contract_summary(prepared),
                      "normalization": prepared["normalization"],
                      "shared_with_control": True, "uses_hidden_answers": False})
    answer = None
    try:
        if name == "artifact_single":
            answer = _single(run, prepared, validator)
        else:
            runner = {"evidence": _evidence, "planning": _planning, "sequential": _sequential}[safe["family"]]
            answer = runner(run, prepared, validator)
    except _BudgetStop:
        # Do not turn a partial artifact into a completed final answer. Traces
        # retain the partial state for diagnosis and all attempted calls count.
        answer = None
    return _finish(name, run, answer, started)


def run_artifact_contracts(task: dict, provider: Any, *, max_calls: int = 5,
                           max_output_tokens: int = 3600, max_input_tokens: int = 24000,
                           public_validator: Callable | None = None) -> dict:
    return _execute("artifact_contracts", task, provider, max_calls=max_calls,
                    max_output_tokens=max_output_tokens, max_input_tokens=max_input_tokens,
                    public_validator=public_validator)


def run_artifact_single(task: dict, provider: Any, *, max_calls: int = 5,
                        max_output_tokens: int = 3600, max_input_tokens: int = 24000,
                        public_validator: Callable | None = None) -> dict:
    return _execute("artifact_single", task, provider, max_calls=max_calls,
                    max_output_tokens=max_output_tokens, max_input_tokens=max_input_tokens,
                    public_validator=public_validator)


def run_contract_adaptive(task: dict, provider: Any, **kwargs) -> dict:
    """Development-fixed policy; no learned routing or hidden answer access."""
    target = "artifact_contracts" if task["family"] == "evidence" else "artifact_single"
    execute = run_artifact_contracts if target == "artifact_contracts" else run_artifact_single
    outcome = execute(task, provider, **kwargs)
    outcome["architecture"] = "contract_adaptive"
    outcome["effective_architecture"] = target
    outcome["trace"].insert(0, {"event": "predeclared_contract_route", "family": task["family"],
                                 "target": target, "learned": False, "uses_hidden_score": False})
    return outcome
