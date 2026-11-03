"""Stratified task sampling with an independently derived seed per task.

The v2 generator walks a cyclic rule enumeration for consecutive task indices.
Here every task gets a separate SHA256-derived phase and payload seed. Semantic
rules can repeat: these are draws from the same finite synthetic population,
not evidence of generalization to unseen repositories or domains.
"""
import hashlib
import json

from .code_tasks import CODE_FAMILIES, generate_code_suite


def ordered_digest(value):
    """Fingerprint JSON mapping order, which can carry config-patch semantics."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def generate_independent_suite(split="dev", per_family=3, seed=2026110306):
    if not isinstance(split, str) or not split:
        raise ValueError("split must be a nonempty string")
    if type(per_family) is not int or per_family < 1:
        raise ValueError("per_family must be a positive integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    tasks = []
    for family in CODE_FAMILIES:
        for index in range(per_family):
            key = f"orgbench-v6|{seed}|{split}|{family}|{index}"
            derived = int.from_bytes(hashlib.sha256(key.encode()).digest()[:16], "big")
            task = next(t for t in generate_code_suite(split, 1, derived) if t["family"] == family)
            task["id"] = f"{split}_{family}_{index:03d}"
            task["metadata"].update(suite_seed=seed, task_seed=derived,
                                    sampler_version="independent_sha256_task_seed_v1")
            tasks.append(task)
    return tasks
