"""可复现的封闭世界任务；执行器只能读取 prompt/schema/public，不能读取 private。

这些合成任务不代表真实软件工程能力。它们隔离证据选择、组合优化和顺序
执行三种计算结构，终局判分完全由确定性程序完成，不使用 LLM 裁判。
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import random
from typing import Any


FAMILIES = ("evidence", "planning", "sequential")


def _rng(seed: int, split: str, family: str, index: int) -> random.Random:
    digest = hashlib.sha256(f"orgbench-v1/{seed}/{split}/{family}/{index}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _pack(family: str, split: str, index: int, public: dict, rules: str,
          schema: dict, private: dict, metadata: dict) -> dict:
    return {
        "id": f"{split}_{family}_{index:03d}",
        "family": family,
        "split": split,
        "prompt": rules + "\n\nINPUT:\n" + json.dumps(public, ensure_ascii=False, separators=(",", ":"))
                  + "\n\nReturn only a JSON object. Output format:\n"
                  + json.dumps(schema, ensure_ascii=False),
        "schema": schema,
        "public": public,
        "private": private,
        "metadata": metadata,
    }


def _eligible_records(public: dict) -> list[dict]:
    cutoff = public["cutoff"]
    revoked = {r["target"] for r in public["revocations"] if r["at"] <= cutoff}
    return [r for r in public["records"] if r["issued"] <= cutoff and r["id"] not in revoked]


def _evidence_answer(public: dict) -> dict:
    eligible = _eligible_records(public)
    facts = {}
    for key in public["requested"]:
        rows = [r for r in eligible if r["key"] == key]
        best = max(rows, key=lambda r: (public["authority"][r["publisher"]],
                                       r["issued"], int(r["id"][1:])))
        facts[key] = {"value": best["value"], "source": best["id"]}
    return {"facts": facts}


def _make_evidence(split: str, index: int, rng: random.Random) -> dict:
    requested = [f"{entity}.{field}" for entity in ("Aster", "Birch", "Cedar")
                 for field in ("status", "quota")]
    public = {
        "cutoff": 20,
        "authority": {"registry": 3, "department": 2, "memo": 1},
        "requested": requested,
        "records": [],
        "revocations": [],
    }
    serial = 1
    for key in requested:
        rows = []
        for k in range(4):
            value = (rng.choice(("active", "paused", "retired", "pending"))
                     if key.endswith("status") else rng.randint(5, 95))
            row = {"id": f"R{serial}", "key": key, "value": value,
                   "publisher": rng.choice(("registry", "department", "memo")),
                   "issued": rng.randint(3, 20) if k < 3 else rng.randint(21, 26)}
            serial += 1
            rows.append(row)
        # 有意放置被撤销的高权威候选，以及尚未生效的撤销；不能只按最新日期选。
        best = max(rows[:3], key=lambda r: (public["authority"][r["publisher"]],
                                           r["issued"], int(r["id"][1:])))
        if rng.random() < 0.65:
            public["revocations"].append({"target": best["id"], "at": rng.randint(10, 20)})
        else:
            public["revocations"].append({"target": best["id"], "at": rng.randint(21, 27)})
        public["records"].extend(rows)
    rng.shuffle(public["records"])
    rules = (
        "Resolve the requested facts at the cutoff. The list order has no meaning. "
        "A record is eligible only if issued <= cutoff and no revocation of its id has at <= cutoff. "
        "Revocation is authoritative regardless of its date relative to the target's issue date. "
        "For EACH requested key, choose the eligible record with highest publisher authority. "
        "Within equal authority choose largest issued; if still tied choose largest NUMERIC R id. "
        "Ignore future records and future revocations. Return both the exact value and its source id. "
        "Every key has at least one eligible record."
    )
    schema = {"facts": {key: {"value": "exact value (string or integer)", "source": "R id"}
                        for key in requested}}
    return _pack("evidence", split, index, public, rules, schema,
                 {"answer": _evidence_answer(public)}, {"record_count": 24, "fact_count": 6})


def _planning_feasibility(public: dict, selected: list[str]) -> list[str]:
    projects = {p["id"]: p for p in public["projects"]}
    violations = []
    if len(selected) != len(set(selected)):
        violations.append("selected contains duplicate ids")
    unknown = set(selected) - projects.keys()
    if unknown:
        violations.append("unknown project ids: " + ",".join(sorted(unknown)))
        return violations
    chosen = set(selected)
    total_cost = sum(projects[p]["cost"] for p in chosen)
    total_hours = sum(projects[p]["hours"] for p in chosen)
    if total_cost > public["budget"]:
        violations.append(f"cost {total_cost} exceeds budget {public['budget']}")
    if total_hours > public["hours_cap"]:
        violations.append(f"hours {total_hours} exceeds cap {public['hours_cap']}")
    for pid in sorted(chosen):
        missing = set(projects[pid]["requires"]) - chosen
        if missing:
            violations.append(f"{pid} missing prerequisites {','.join(sorted(missing))}")
    for group in public["exclusive_groups"]:
        if len(chosen.intersection(group)) > 1:
            violations.append("exclusive group violated: " + ",".join(group))
    return violations


def _planning_value(public: dict, selected: list[str]) -> int:
    chosen = set(selected)
    value = sum(p["value"] for p in public["projects"] if p["id"] in chosen)
    return value + sum(s["bonus"] for s in public["synergies"]
                       if set(s["pair"]).issubset(chosen))


def _planning_optimum(public: dict) -> tuple[int, list[str]]:
    ids = [p["id"] for p in public["projects"]]
    best_value, best_selection = -1, []
    for length in range(len(ids) + 1):
        for subset in itertools.combinations(ids, length):
            selected = list(subset)
            if not _planning_feasibility(public, selected):
                value = _planning_value(public, selected)
                if value > best_value:
                    best_value, best_selection = value, selected
    return best_value, best_selection


def _make_planning(split: str, index: int, rng: random.Random) -> dict:
    n = 11 + index % 2
    projects = []
    for k in range(n):
        requires = []
        if k >= 2 and rng.random() < 0.55:
            requires = [f"P{rng.randint(1, k)}"]
        if k >= 5 and rng.random() < 0.20:
            requires = list(dict.fromkeys(requires + [f"P{rng.randint(1, k)}"]))
        projects.append({"id": f"P{k + 1}", "cost": rng.randint(3, 13),
                         "hours": rng.randint(2, 11), "value": rng.randint(6, 30),
                         "requires": requires})
    ids = [p["id"] for p in projects]
    exclusive = [rng.sample(ids, 3), rng.sample(ids, 2)]
    public = {
        "budget": round(sum(p["cost"] for p in projects) * rng.uniform(0.38, 0.53)),
        "hours_cap": round(sum(p["hours"] for p in projects) * rng.uniform(0.38, 0.53)),
        "projects": projects,
        "exclusive_groups": exclusive,
        "synergies": [{"pair": rng.sample(ids, 2), "bonus": rng.randint(7, 24)} for _ in range(4)],
    }
    optimum, selected = _planning_optimum(public)
    rules = (
        "Select a feasible subset of projects MAXIMIZING total utility. Utility is the sum of "
        "selected project values PLUS every synergy bonus whose two projects are both selected. "
        "Total cost must be <= budget, total hours <= hours_cap, all requires must be selected, "
        "and at most one project from each exclusive group may be selected. A project is counted "
        "once even if several projects require it. Empty selection is allowed. "
        "All numeric quantities are integers. Any globally optimal feasible subset is accepted; "
        "the order of selected ids does not matter. Return selected ids only."
    )
    return _pack("planning", split, index, public, rules,
                 {"selected": ["P id", "..."]},
                 {"answer": {"selected": selected}, "optimal_value": optimum},
                 {"project_count": n, "constraint_count": 2 + len(exclusive), "synergy_count": 4})


def _sequential_answer(public: dict) -> dict:
    balances = dict(public["initial_balances"])
    frozen = set(public["initial_frozen"])
    events = public["events"]
    revoked = {event["target"] for event in events if event["op"] == "cancel"}
    seen = set()
    accepted = 0
    for event in events:
        if event["op"] == "cancel" or event["id"] in revoked or event["id"] in seen:
            continue
        seen.add(event["id"])
        op = event["op"]
        account = event.get("account")
        if op == "credit":
            balances[account] += event["amount"]
        elif op == "debit":
            if account in frozen or balances[account] < event["amount"]:
                continue
            balances[account] -= event["amount"]
        elif op == "transfer":
            src, dst = event["from"], event["to"]
            if src in frozen or dst in frozen or balances[src] < event["amount"]:
                continue
            balances[src] -= event["amount"]
            balances[dst] += event["amount"]
        elif op == "freeze":
            frozen.add(account)
        elif op == "unfreeze":
            frozen.discard(account)
        elif op == "bonus_if":
            if balances[event["if_account"]] < event["threshold"]:
                continue
            balances[account] += event["amount"]
        else:
            raise ValueError(f"Unknown generated operation {op}")
        accepted += 1
    return {"balances": balances, "frozen": sorted(frozen), "accepted": accepted}


def _make_sequential(split: str, index: int, rng: random.Random) -> dict:
    accounts = ("A", "B", "C")
    public = {"initial_balances": {a: rng.randint(70, 150) for a in accounts},
              "initial_frozen": [], "events": []}
    operations = ("transfer", "transfer", "credit", "debit", "freeze", "unfreeze", "bonus_if")
    for k in range(27 + index % 4):
        op = rng.choice(operations)
        event = {"id": f"E{k + 1}", "op": op}
        if op == "transfer":
            src, dst = rng.sample(accounts, 2)
            event.update({"from": src, "to": dst, "amount": rng.randint(15, 120)})
        else:
            event["account"] = rng.choice(accounts)
            if op in ("credit", "debit", "bonus_if"):
                event["amount"] = rng.randint(10, 90)
            if op == "bonus_if":
                event.update({"if_account": rng.choice(accounts), "threshold": rng.randint(60, 200)})
        public["events"].append(event)
    originals = copy.deepcopy(public["events"])
    # 同一 id 的后续副本可能携带不同负载；规则是 first-seen，而不是 latest-wins。
    for original in rng.sample(originals, 4):
        duplicate = dict(original)
        if "amount" in duplicate:
            duplicate["amount"] += rng.randint(3, 19)
        pos = rng.randint(0, len(public["events"]))
        public["events"].insert(pos, duplicate)
    for k, target in enumerate(rng.sample(originals, 3)):
        cancel = {"id": f"C{k + 1}", "op": "cancel", "target": target["id"]}
        public["events"].insert(rng.randint(0, len(public["events"])), cancel)
    rules = (
        "Replay this ledger and return its final state. Exact rules: (1) Before replay, collect "
        "ALL cancel targets anywhere in the input; every occurrence of each targeted non-cancel "
        "id is removed, even occurrences before the cancel. Cancel events do not count as accepted. "
        "(2) Replay the remaining events in LIST ORDER. For each non-cancel id, only its FIRST "
        "occurrence is processed; mark it seen even if rejected by a condition. Later duplicates "
        "never execute, even with different payloads. (3) credit adds amount even if account is "
        "frozen. debit subtracts only if that account is unfrozen and has enough funds. transfer "
        "subtracts from 'from' and adds to 'to' only if BOTH accounts are unfrozen and source has "
        "enough funds. Rejected operations change nothing. freeze/unfreeze always execute and "
        "set/clear the account's frozen state, even if already set/clear. bonus_if executes iff "
        "the CURRENT balance of if_account is >= threshold, then credits amount to account even "
        "if frozen. (4) accepted counts executed unique non-revoked events, INCLUDING freeze, "
        "unfreeze and qualifying bonus_if; rejected, duplicate and revoked events do not count. "
        "Return balances, frozen account ids (any order), and accepted count."
    )
    schema = {"balances": {"A": "integer", "B": "integer", "C": "integer"},
              "frozen": ["account id, if frozen"], "accepted": "integer"}
    return _pack("sequential", split, index, public, rules, schema,
                 {"answer": _sequential_answer(public)}, {"event_count": len(public["events"]),
                                                          "cancel_count": 3, "duplicate_count": 4})


def generate_suite(split: str = "dev", per_family: int = 4, seed: int = 20261102) -> list[dict]:
    """每个 split/family/index 使用独立 SHA256 随机流；不随并发或生成顺序变化。"""
    if type(per_family) is not int or per_family < 1:
        raise ValueError("per_family must be a positive integer")
    if not isinstance(split, str) or not split:
        raise ValueError("split must be a nonempty string")
    makers = {"evidence": _make_evidence, "planning": _make_planning, "sequential": _make_sequential}
    result = []
    for family in FAMILIES:
        for index in range(per_family):
            task = makers[family](split, index, _rng(seed, split, family, index))
            task["metadata"]["suite_seed"] = seed
            task["metadata"]["generator_version"] = "orgbench-v1"
            result.append(task)
    return result


def _is_int(value: Any) -> bool:
    return type(value) is int


def validate_public(task: dict, answer: dict) -> list[str]:
    """公共反馈只查格式/来源支持/约束可行性，绝不读取 task['private']。

    evidence 不检查是否选中了最高优先级；planning 不检查最优性；sequential
    不运行状态机比较最终答案。因此反馈不能直接给执行器泄露隐藏终局答案。
    """
    if not isinstance(answer, dict):
        return ["answer must be a JSON object"]
    family, public = task["family"], task["public"]
    violations = []
    if family == "evidence":
        facts = answer.get("facts")
        if not isinstance(facts, dict):
            return ["facts must be an object"]
        if set(facts) != set(public["requested"]):
            violations.append("facts must contain exactly the requested keys")
        records = {r["id"]: r for r in public["records"]}
        eligible = {r["id"] for r in _eligible_records(public)}
        for key, fact in facts.items():
            if not isinstance(fact, dict) or "value" not in fact or "source" not in fact:
                violations.append(f"{key} must have value and source")
                continue
            source = fact["source"]
            if not isinstance(source, str) or source not in records:
                violations.append(f"{key} has unknown source")
                continue
            record = records[source]
            if record["key"] != key:
                violations.append(f"{key} source is for another key")
            if fact["value"] != record["value"] or type(fact["value"]) is not type(record["value"]):
                violations.append(f"{key} value is not supported by its source")
            if source not in eligible:
                violations.append(f"{key} source is future or revoked")
    elif family == "planning":
        selected = answer.get("selected")
        if not isinstance(selected, list) or any(not isinstance(p, str) for p in selected):
            return ["selected must be a list of project id strings"]
        violations.extend(_planning_feasibility(public, selected))
    elif family == "sequential":
        balances = answer.get("balances")
        if not isinstance(balances, dict) or set(balances) != set(public["initial_balances"]):
            violations.append("balances must have exactly all account ids")
        elif any(not _is_int(v) or v < 0 for v in balances.values()):
            violations.append("balances must be nonnegative integers")
        frozen = answer.get("frozen")
        if (not isinstance(frozen, list) or any(not isinstance(a, str) for a in frozen)
                or len(frozen) != len(set(frozen))
                or not set(frozen).issubset(public["initial_balances"])):
            violations.append("frozen must contain distinct known account ids")
        accepted = answer.get("accepted")
        if not _is_int(accepted) or accepted < 0 or accepted > len(public["events"]):
            violations.append("accepted must be a nonnegative integer no larger than event count")
    else:
        raise ValueError(f"Unknown family: {family}")
    return violations


def evaluate(task: dict, answer: dict) -> dict:
    """独立终局裁判。planning 接受全部最优解；source id 与证据值共同判分。"""
    violations = validate_public(task, answer)
    if not isinstance(answer, dict):
        return {"success": False, "score": 0.0, "violations": violations}
    family, public, private = task["family"], task["public"], task["private"]
    if family == "evidence":
        expected = private["answer"]["facts"]
        facts = answer.get("facts", {})
        if not isinstance(facts, dict):
            score = 0.0
        else:
            correct = 0
            for key, value in expected.items():
                got = facts.get(key)
                if (isinstance(got, dict) and got.get("source") == value["source"]
                        and got.get("value") == value["value"]
                        and type(got.get("value")) is type(value["value"])):
                    correct += 1
            score = correct / len(expected)
        success = not violations and score == 1.0
        if not success and not violations:
            violations.append("one or more facts did not use the priority-winning source")
    elif family == "planning":
        if violations:
            score, success = 0.0, False
        else:
            utility = _planning_value(public, answer["selected"])
            optimal = private["optimal_value"]
            score = utility / optimal if optimal else 1.0
            success = utility == optimal
            if not success:
                violations.append(f"feasible but suboptimal utility {utility}; optimum {optimal}")
    elif family == "sequential":
        expected = private["answer"]
        balances = answer.get("balances", {})
        if not isinstance(balances, dict):
            balances = {}
        correct = sum(_is_int(balances.get(a)) and balances[a] == value
                      for a, value in expected["balances"].items())
        frozen = answer.get("frozen")
        if isinstance(frozen, list) and all(isinstance(x, str) for x in frozen):
            correct += int(set(frozen) == set(expected["frozen"]))
        correct += int(_is_int(answer.get("accepted")) and answer["accepted"] == expected["accepted"])
        score = correct / (len(expected["balances"]) + 2)
        success = not violations and score == 1.0
        if not success and not violations:
            violations.append("final state differs from deterministic ledger replay")
    else:
        raise ValueError(f"Unknown family: {family}")
    return {"success": bool(success), "score": float(score), "violations": violations}
