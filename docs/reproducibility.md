# Reproduction

## Offline checks

Run from the repository root with Python 3.11 or newer:

```bash
python -m unittest discover -s tests
python -m orgbench.study_v6 --help
```

Core tests use the standard library. They must not require provider credentials or make live model requests. Plotting and native-pilot cryptography are optional and are not installed in the main CI job.

## Public demonstration seed

Use **202611039901** for newly generated public reproduction examples. It is dedicated to demonstrations and must not be substituted with an active study holdout seed.

Both stage seeds and task counts are registered in [study_v6_plan.json](study_v6_plan.json): development uses three tasks per family and confirmation uses 20. The plan also locks the model and per-task resource settings.

For example, this creates only local public tasks, without a model request:

```python
import json
from pathlib import Path
from orgbench.task_suite_v6 import generate_independent_suite

plan = json.loads(Path("docs/study_v6_plan.json").read_text(encoding="utf-8"))
tasks = generate_independent_suite(
    split="dev", per_family=plan["dev"]["per_family"], seed=plan["dev"]["seed"]
)
public = [{key: value for key, value in task.items() if key != "private"} for task in tasks]
Path("public_repro.json").write_text(
    json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8"
)
```

The generator can construct reference cases locally. This example intentionally writes only the public projection. It is a smoke/reproduction dataset, not the active confirmation dataset and not evidence of benchmark performance by itself.

## Live experiments

The v6 command is `python -m orgbench.study_v6`. The following preparation command is offline and requires no provider credentials. It writes newly generated public and private files locally under ignored `runs/`; do not publish those files wholesale.

```bash
python -m orgbench.study_v6 --out runs/repro_dev --split dev --model deepseek-v4-pro --thinking disabled --workers 4 --protocol docs/protocol_v6.md --plan docs/study_v6_plan.json --prepare-only
```

To execute the reproduction development run, configure your own authorized provider locally and explicitly run the same command **without** `--prepare-only`. This contacts the configured provider; it is not an offline check. Do not place credential values in commands saved to the repository or in issue reports. Respect any provider-stop instruction before executing it.

After a complete valid development run, freeze its selection offline:

```bash
python -m orgbench.study_v6 --out runs/repro_dev --plan docs/study_v6_plan.json --select-only
```

The second public reproduction seed is **202611039902**. Only after selection exists, prepare the separate 60-task confirmation dataset:

```bash
python -m orgbench.study_v6 --out runs/repro_confirm --split holdout --model deepseek-v4-pro --thinking disabled --workers 4 --protocol docs/protocol_v6.md --plan docs/study_v6_plan.json --selection runs/repro_dev/selection.json --prepare-only
```

Removing `--prepare-only` explicitly executes that new confirmation run. Its results are a public reproduction study, not the original registered holdout. The same source/protocol hashes must remain unchanged between development selection and confirmation; the runner rejects a mismatched selection.

The runner reads omitted seed/per-family values from the stage plan. If explicitly supplied, they must be the exact registered values. Do not shrink the registered study to a one-task smoke run or substitute an arbitrary seed by CLI override. For a different experiment, create a new plan/study identity, update its protocol, use new output directories and repeat development selection; the previous selection's plan hash must not be reused.

The public protocol template deliberately has a different hash from the original registration. An original registration, when approved for publication after retirement, is kept separately as `protocol_v6_original.md`. Do not overwrite an original manifest or claim that the public template hash is its registered hash.

The public machine plan also has a separate study identity/hash. Do not replace it with the root workspace's active plan. The actual original protocol/plan are published only after the study is retired and approved for release.

Keep development selection separate from fresh confirmation. Freeze model settings, prompts, tools, per-task budgets, stage allocation, executor policy, candidate selection and statistical endpoints before confirmation. Preserve all attempts and failures locally, then export only reviewed aggregates.

Provider sampling is not controlled by the task-generation seed. A reproducible task manifest and offline analysis do not promise bit-for-bit reproduction of a stochastic hosted model's answers or underlying weights.

## Historical v5 result

[The curated v5 aggregate](results-v5.md) reports the completed original experiment. This public tree intentionally excludes raw provider logs and private/current cases. Fresh runs are new replications, not replacements for the archived result. Compare model, generator and protocol revisions before comparing outcomes.

If included by the exporter, `historical/v5/orgbench/` preserves the retired v5 source snapshot for source-hash inspection. A source snapshot alone does not reproduce private archived inputs, a hosted model's stochastic answers, or a complete historical run. It is separate from the current v6 package.

## Native backend

Native agents require fresh, public-only contexts and separate result files. A researcher who has seen references or hidden answers must not serve as a solver. Unknown native tokens, model identifiers or provider charges remain null; a native pilot is not a cost-matched substitute for an API arm.
