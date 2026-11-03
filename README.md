# Agent Org Bench

**Latest v6r1 confirmation:** the new router solved **39/60 (65.0%)**, versus **47/60 (78.3%)** for single-agent self-review. None of the four preregistered superiority comparisons passed. Negative results remain part of this comparative workbench. [Latest results](docs/results-v6.md).

A research workbench for building and comparing agent coordination mechanisms under shared tools and declared resource limits.

[简体中文](README.zh-CN.md) · [Architectures and flow diagrams](docs/architecture_catalog.md) · [Concrete task examples](docs/task_examples.md) · [Conclusions](docs/conclusions.md) · [Reproduction](docs/reproducibility.md) · [Known limitations](docs/known_limitations.md)

The project asks **which coordination mechanisms help which tasks**, rather than declaring one universally best organization. Implementations are simplified mechanism baselines, not official reproductions of DSH, AutoGen, or other frameworks.

## v6 results

Completed 81 development and 300 fresh-confirmation task runs; frozen candidate: `adaptive_tools`. Development self-review solved 9/9 and the candidate 8/9; selection was not overall first place.

Primary vs single_self_review: superiority not confirmed. Secondary declarations separately: `single_tool`=not confirmed; `hierarchy_tool`=not confirmed; `best_of_three`=not confirmed.

Non-confirmation is not equivalence or noninferiority; token ratios are descriptive.

[Bilingual results](docs/results-v6.md) · [Study status](docs/study-status.md)

![Observed success on the 60-task confirmation](results/v6/confirmation_success.png)

![Exploratory task-family comparison, 20 tasks per cell](results/v6/task_family_heatmap.png)

The [paired-difference plot](results/v6/paired_quality_deltas.png) shows the four candidate comparisons and their original marginal 95% intervals. Family point estimates are exploratory; they are not confirmed task-specific winners.

## Historical v5 evidence (separate cohort)

The completed v5 confirmation used one model, three families of generated code-repair tasks, and 90 independent tasks per strategy:

| Strategy | Tasks solved | Success rate |
| --- | ---: | ---: |
| Public-feature router (`adaptive_tools`) | 66/90 | 73.33% |
| Tool single agent (`single_tool`) | 44/90 | 48.89% |
| Simplified supervisor–worker (`hierarchy_tool`) | 41/90 | 45.56% |

Both preregistered paired quality comparisons passed. **The preregistered token-efficiency test did not pass.** The observed token ratio against the single agent was 0.936; its 95% paired interval was approximately [0.801, 1.100]. See [v5 results and limitations](docs/results-v5.md).

These findings do not establish a pure topology effect: extra review, prompts, context boundaries, and allocation rules differ. The router score is constant within each task template, and two routed task families execute the same implementation as the single-agent baseline. V6 added call/stage-matched self-review and did not confirm an advantage for the new strategy.

## What was evaluated

Nine executable policies vary context access, scheduling, review, selection and stopping. Twelve historical named configurations are separately documented; they do not form a common 21-arm leaderboard. See the [individual architecture cards and diagrams](docs/architecture_catalog.md).

Controls are one-shot solving (development only), public-failure repair by one solver, same-context self-review (primary), router–workers hierarchy and three independent complete candidates selected by public tests. New candidates are two-branch bazaar, independent audit, fixed routing and evidence gating. Candidate selection among four treatments is not a claim of beating the controls.

Three synthetic repair families cover version/conflict merging, a stateful ledger with event invariants, and conditional/dependency-driven configuration. Every task includes a deliberately wrong starter, complete rules and three public examples. Final scoring uses 30 hidden cases plus input-immutability checks. Public passes alone do not establish correctness.

Read the [concrete input/output examples](docs/task_examples.md) or inspect [all retired public task specifications](datasets/README.md). These are restricted-AST mechanism experiments, not a completed SWE-bench or official-framework comparison.

## Offline setup

Python **3.11 or newer**. The core uses the standard library.

```bash
python -m unittest discover -s tests
python -m orgbench.study_v6 --help
```

The test suite is offline. CI does not run model experiments or receive provider credentials. Optional report plots use `matplotlib`; optional native-pilot tooling uses `cryptography`, neither required by the core test workflow.

```bash
python -m pip install -e ".[report]"
# Only if working with the separate optional native-pilot tooling:
python -m pip install -e ".[native]"
```

Model execution is explicit. Follow the CLI help and [reproduction guide](docs/reproducibility.md); a local test run or package import must not silently start a provider request.

## What is measured

- Hidden-test task success and partial correctness, separately from public-example success.
- Actual provider input/output tokens, cached input, logical calls and HTTP attempts when observable.
- Infrastructure failures, invalid outputs, budget stops and execution limits.
- Quality–resource trade-offs; observed Pareto points are not automatically confirmed improvements.

Generated code runs in a bounded AST interpreter inside a resource-limited process. This supports a restricted Python subset, not arbitrary production Python or a general hostile-code sandbox.

## Reproducibility and data

Public demonstrations use a dedicated reproduction seed, **202611039901**, not the active study holdout. The release excludes raw runs, provider logs, active private cases, credentials, account information and native-pilot encrypted material or keys. Different generator seeds do not imply a new real-world task distribution.

The [public machine plan](docs/study_v6_plan.json) fixes development/confirmation seeds, sample sizes and runtime limits. CLI mismatches are rejected; a different experiment requires a new plan and study identity. The public protocol/plan hashes differ from the original registration, which is archived separately only after study retirement.

Native-agent observations are recorded separately from API experiments. Unobservable native tokens or provider charges remain unknown; they are never filled with zero or merged into API efficiency comparisons.

## License

The author has not selected a project license. [LICENSE-NOTICE.md](LICENSE-NOTICE.md) is a status notice, not a license grant. No MIT, Apache or other license is implied.
