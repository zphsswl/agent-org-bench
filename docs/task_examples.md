# Concrete task examples / 具体任务示例

The benchmark asks for a complete `solve(payload)` implementation that repairs a deliberately wrong starter. The three families are version conflict resolution, an idempotent stateful ledger and conditional configuration resolution. These are generated function-level tasks in a restricted Python subset, not real-repository or SWE-bench tasks.

本页给出每族一道完整公开题目的规格、规则开关，以及一个真实公开输入和预期输出。输入较长时可展开查看。它们来自公开演示种子 **202611039901**，调用 `generate_independent_suite('dev', 1, 202611039901)` 后只保存 `id/family/public` 投影。**没有模型求解或成绩，也不是正式确认实验的成绩题集。**

机器可读版本：[public_demo_tasks.json](../examples/public_demo_tasks.json)。其中保留每题的全部三个公开例、错误starter和允许语言子集；没有私有案例、任务私有字段或隐藏评分。JSON映射插入顺序保留，不能任意排序配置patch的键后声称题目未变。

Every strategy receives the same public material for a given scored task. Actual public execution can inform repair; terminal cases stay outside the solver loop. Passing a displayed example does not establish full task success. [Evaluation methods](methods.md) explain the resource and delivery conditions.

## 1. Version conflict resolution

Task ID: `dev_code_versions_000`. Function: `solve(payload)`. This is public demonstration example 1 of 3.

### Complete public specification

Implement a document-version resolver. payload has cutoff and records with UNIQUE string ids. Each set/delete record has id,key,kind,time,authority and sets additionally have value. Each retract record has id,kind='retract',target,time,authority; targets are set/delete ids, never retract ids. Records are not time-sorted. First exclude every record with time > cutoff. A remaining retract can revoke its exact target: scope='global' ignores relative times; scope='not_after_retractor' permits revoking only targets with target.time <= retract.time. If qualified_retractions=true the retract must also have at least the target's authority under the configured authority direction; otherwise its authority does not matter. Revocations are collected before winner selection, independent of list position. Group remaining set/delete candidates by key, lowercasing keys only when keys='lower'. Prefer larger authority if authority='higher', smaller if 'lower'. Prefer larger time. priority selects which of those two criteria is primary; the other is secondary. Exact ties use first or last INPUT position, or lexicographically LARGEST full string id when tie='id_lex' (not numeric comparison). A winning delete omits its key from values but DOES appear in sources. Return {'values':{key:value},'sources':{key:winner_id}}. Only keys with eligible winners appear in sources. Return fresh objects; do not mutate input. IMPORTANT: solve must not mutate payload, including any nested object; return fresh result objects.

### Per-task rules

```json
{
  "authority": "lower",
  "priority": "authority_then_time",
  "keys": "case_sensitive",
  "tie": "id_lex",
  "qualified_retractions": false,
  "retraction_scope": "not_after_retractor"
}
```

<details>
<summary>Full public input / 完整公开输入</summary>

```json
{
  "cutoff": 6,
  "records": [
    {
      "id": "D7x3",
      "kind": "set",
      "key": "mode",
      "time": 4,
      "authority": 3,
      "value": 0
    },
    {
      "id": "Future",
      "kind": "set",
      "key": "quota",
      "value": 999,
      "time": 10,
      "authority": 1
    },
    {
      "id": "D7x4",
      "kind": "set",
      "key": "Mode",
      "time": 3,
      "authority": 1,
      "value": "red"
    },
    {
      "id": "D6x5",
      "kind": "set",
      "key": "mode",
      "time": 3,
      "authority": 1,
      "value": 7
    },
    {
      "id": "Revoke0",
      "kind": "retract",
      "target": "Z2",
      "time": 3,
      "authority": 3
    },
    {
      "id": "Z2",
      "kind": "set",
      "key": "Mode",
      "value": "tie-last",
      "time": 4,
      "authority": 2
    },
    {
      "id": "D7x9",
      "kind": "set",
      "key": "Mode",
      "time": 0,
      "authority": 2,
      "value": "green"
    },
    {
      "id": "D3x1",
      "kind": "set",
      "key": "Mode",
      "time": 5,
      "authority": 2,
      "value": "red"
    },
    {
      "id": "D9x6",
      "kind": "delete",
      "key": "quota",
      "time": 6,
      "authority": 1
    },
    {
      "id": "Z10",
      "kind": "set",
      "key": "Mode",
      "value": "tie-first",
      "time": 4,
      "authority": 2
    },
    {
      "id": "D6x7",
      "kind": "set",
      "key": "mode",
      "time": 6,
      "authority": 1,
      "value": 7
    },
    {
      "id": "D8x2",
      "kind": "set",
      "key": "Mode",
      "time": 5,
      "authority": 3,
      "value": 7
    },
    {
      "id": "Revoke1",
      "kind": "retract",
      "target": "D3x1",
      "time": 7,
      "authority": 1
    },
    {
      "id": "D5x0",
      "kind": "delete",
      "key": "mode",
      "time": 2,
      "authority": 3
    },
    {
      "id": "Delete",
      "kind": "delete",
      "key": "region",
      "time": 6,
      "authority": 3
    },
    {
      "id": "D8x8",
      "kind": "set",
      "key": "region",
      "time": 6,
      "authority": 1,
      "value": "red"
    }
  ]
}
```

</details>

### Expected public output

```json
{
  "values": {
    "mode": 7,
    "Mode": "red",
    "region": "red"
  },
  "sources": {
    "mode": "D6x7",
    "Mode": "D7x4",
    "quota": "D9x6",
    "region": "D8x8"
  }
}
```

### What this example checks

The future record at time 10 is excluded by cutoff 6. Lower authority is preferred before time, and keys are case-sensitive. Revoke0 cannot revoke its later-time target under not_after_retractor. The winning quota delete is absent from values but remains in sources.

## 2. Idempotent stateful ledger

Task ID: `dev_code_ledger_000`. Function: `solve(payload)`. This is public demonstration example 1 of 3.

### Complete public specification

Implement an idempotent event ledger. payload contains initial balances (known account ids), initial frozen account ids, and events in execution order. All amounts and thresholds are nonnegative integers; all referenced accounts exist. cancel targets non-cancel event ids. When cancel='global', collect all cancel targets first and skip all occurrences of those ids, including earlier events. When cancel='forward', process cancel positions in order and block only later target occurrences; never undo earlier effects. cancel never enters accepted. For dedup='first_seen', mark each uncancelled unseen non-cancel id seen BEFORE testing its condition, even if rejected. For dedup='first_applied', mark only after execution: a rejected id can execute on a later occurrence with different payload. Always ignore already seen ids. credit adds amount, including to frozen accounts only if credit_frozen=true. debit executes only on an unfrozen account with enough funds. transfer requires enough source funds and unfrozen source; destination must also be unfrozen iff transfer_requires_unfrozen_destination. freeze/thaw set/clear frozen; a no-op counts as applied iff count_noop_freeze=true. bonus tests CURRENT balance of if_account against threshold using >= for ge or > for gt; if true it acts as credit to account with the same frozen rule. Rejected operations do nothing. A no-op freeze/thaw rejected for counting still leaves the same frozen state. Return {'balances':{account:int},'frozen':sorted_account_ids,'accepted':[executed event ids in execution order]}. Every applied event, including allowed no-ops, enters accepted once. IMPORTANT: solve must not mutate payload, including any nested object; return fresh result objects.

### Per-task rules

```json
{
  "cancel": "forward",
  "dedup": "first_applied",
  "credit_frozen": true,
  "transfer_requires_unfrozen_destination": false,
  "count_noop_freeze": true,
  "bonus_comparison": "ge"
}
```

<details>
<summary>Full public input / 完整公开输入</summary>

```json
{
  "initial": {
    "A": 45,
    "B": 5,
    "C": 63
  },
  "frozen": [],
  "events": [
    {
      "id": "retry",
      "op": "debit",
      "account": "A",
      "amount": 999
    },
    {
      "id": "retry",
      "op": "credit",
      "account": "A",
      "amount": 2
    },
    {
      "id": "noop",
      "op": "thaw",
      "account": "B"
    },
    {
      "id": "cancel0",
      "op": "cancel",
      "target": "E11"
    },
    {
      "id": "equal",
      "op": "bonus",
      "account": "C",
      "if_account": "B",
      "threshold": 5,
      "amount": 3
    },
    {
      "id": "E0",
      "op": "credit",
      "account": "C",
      "amount": 45
    },
    {
      "id": "E1",
      "op": "thaw",
      "account": "C"
    },
    {
      "id": "cancel1",
      "op": "cancel",
      "target": "E0"
    },
    {
      "id": "E0",
      "op": "credit",
      "account": "C",
      "amount": 4
    },
    {
      "id": "E2",
      "op": "thaw",
      "account": "B"
    },
    {
      "id": "E3",
      "op": "thaw",
      "account": "A"
    },
    {
      "id": "E4",
      "op": "thaw",
      "account": "A"
    },
    {
      "id": "E5",
      "op": "bonus",
      "account": "C",
      "amount": 66,
      "if_account": "A",
      "threshold": 38
    },
    {
      "id": "E6",
      "op": "debit",
      "account": "A",
      "amount": 34
    },
    {
      "id": "E7",
      "op": "freeze",
      "account": "A"
    },
    {
      "id": "E8",
      "op": "credit",
      "account": "C",
      "amount": 77
    },
    {
      "id": "E9",
      "op": "freeze",
      "account": "C"
    },
    {
      "id": "E7",
      "op": "freeze",
      "account": "A"
    },
    {
      "id": "E10",
      "op": "credit",
      "account": "B",
      "amount": 55
    },
    {
      "id": "E11",
      "op": "credit",
      "account": "C",
      "amount": 33
    }
  ]
}
```

</details>

### Expected public output

```json
{
  "balances": {
    "A": 13,
    "B": 60,
    "C": 254
  },
  "frozen": [
    "A",
    "C"
  ],
  "accepted": [
    "retry",
    "noop",
    "equal",
    "E0",
    "E1",
    "E2",
    "E3",
    "E4",
    "E5",
    "E6",
    "E7",
    "E8",
    "E9",
    "E10"
  ]
}
```

### What this example checks

The first retry debit is rejected for insufficient balance, so first_applied does not consume its ID; the second retry credit can execute. Allowed no-op thaw events enter accepted. Forward cancellations do not undo earlier effects and block later target occurrences. Final balances are A=13, B=60 and C=254.

## 3. Conditional configuration resolution

Task ID: `dev_code_config_000`. Function: `solve(payload)`. This is public demonstration example 1 of 3.

### Complete public specification

Implement conditional configuration resolution. payload has defaults and layers, each with UNIQUE id, priority, requires (layer ids), when (null or condition), values (a patch). Normalize all default/patch/condition keys to lower case iff keys='lower'; otherwise keep case. Within a mapping process keys in their insertion order, including normalization collisions. Copy defaults as initial config, preserving null defaults. Sort layers by priority ascending or descending per priority_order; ties use original input order for tie='input' or lexicographically ASCENDING full id for tie='id_lex'. Requires means ALL listed ids must have actually applied, including ids absent from input which never apply. For single_pass, visit the sorted list once and permanently skip unmet dependencies. For revisit, defer only unmet-dependency layers; after a full pass retry deferred layers in the same sorted relative order. Stop when a pass applies no layers. Conditions are tested only when dependencies are satisfied: exists requires key membership (even null), eq requires membership and equality to equals. condition_context='snapshot' uses the normalized defaults; 'live' uses the current config. A false condition permanently rejects that layer and is NEVER retried. For each applied patch, if null='delete' and value is null remove that key regardless of merge; else overwrite when merge='overwrite', or only insert absent keys when merge='preserve'. Applied includes eligible true-condition layers even if their patches change nothing. Return {'config':final_mapping,'applied':[layer ids in actual application order],'blocked':[all unapplied ids in ORIGINAL input order]}. Cycles, missing dependencies and condition-rejected prerequisites stay unapplied. IMPORTANT: solve must not mutate payload, including any nested object; return fresh result objects.

### Per-task rules

```json
{
  "dependencies": "revisit",
  "priority_order": "ascending",
  "tie": "id_lex",
  "condition_context": "snapshot",
  "null": "delete",
  "merge": "overwrite",
  "keys": "case_sensitive"
}
```

<details>
<summary>Full public input / 完整公开输入</summary>

```json
{
  "defaults": {
    "Mode": "off",
    "mode": "on",
    "quota": 0,
    "obsolete": null
  },
  "layers": [
    {
      "id": "L0",
      "priority": 2,
      "requires": [
        "L10"
      ],
      "when": null,
      "values": {
        "new": "from-dependent"
      }
    },
    {
      "id": "L8",
      "priority": 1,
      "requires": [],
      "when": {
        "key": "mode",
        "op": "exists"
      },
      "values": {
        "new": "on",
        "mode": "on"
      }
    },
    {
      "id": "L9",
      "priority": 2,
      "requires": [
        "L5",
        "L0"
      ],
      "when": null,
      "values": {
        "quota": "on",
        "obsolete": "off",
        "mode": "off"
      }
    },
    {
      "id": "L1",
      "priority": 2,
      "requires": [],
      "when": {
        "key": "Mode",
        "op": "eq",
        "equals": "on"
      },
      "values": {
        "quota": 7
      }
    },
    {
      "id": "L5",
      "priority": 3,
      "requires": [],
      "when": {
        "key": "mode",
        "op": "exists"
      },
      "values": {
        "new": 3,
        "mode": "on"
      }
    },
    {
      "id": "L4",
      "priority": 3,
      "requires": [
        "L5",
        "L10"
      ],
      "when": {
        "key": "new",
        "op": "eq",
        "equals": 3
      },
      "values": {
        "new": 3
      }
    },
    {
      "id": "L6",
      "priority": 2,
      "requires": [
        "L4"
      ],
      "when": {
        "key": "Mode",
        "op": "eq",
        "equals": "on"
      },
      "values": {
        "mode": 1
      }
    },
    {
      "id": "L10",
      "priority": 3,
      "requires": [],
      "when": null,
      "values": {
        "Mode": "on",
        "quota": null
      }
    },
    {
      "id": "L3",
      "priority": 2,
      "requires": [
        "L9",
        "L5"
      ],
      "when": null,
      "values": {
        "mode": 3
      }
    },
    {
      "id": "L7",
      "priority": 2,
      "requires": [
        "L10",
        "L2"
      ],
      "when": null,
      "values": {
        "new": "on"
      }
    },
    {
      "id": "L2",
      "priority": 0,
      "requires": [],
      "when": null,
      "values": {
        "new": "off"
      }
    }
  ]
}
```

</details>

### Expected public output

```json
{
  "config": {
    "Mode": "on",
    "mode": 3,
    "obsolete": "off",
    "new": "on",
    "quota": "on"
  },
  "applied": [
    "L2",
    "L8",
    "L10",
    "L5",
    "L0",
    "L7",
    "L9",
    "L3"
  ],
  "blocked": [
    "L1",
    "L4",
    "L6"
  ]
}
```

### What this example checks

Layers may be revisited when dependencies later become satisfied. Conditions use the original defaults snapshot: L1 is rejected because default Mode is off, even though a later applied layer writes Mode=on. L4 cannot satisfy its snapshot condition on new, so its dependent L6 remains blocked. Key case and patch insertion order are part of the specification.


## Reproduce only the public projection / 只复现公开投影

Run from the repository root; this does not contact a model:

```python
import json
from orgbench.task_suite_v6 import generate_independent_suite

tasks = generate_independent_suite("dev", 1, 202611039901)
public_demo = [
    {"id": task["id"], "family": task["family"], "public": task["public"]}
    for task in tasks
]
print(json.dumps(public_demo, ensure_ascii=False, indent=2))
```

The generator can construct additional cases locally, but this example exports only its explicit public projection. Do not publish an unfiltered task object or treat these demonstration examples as a fresh blind confirmation.
