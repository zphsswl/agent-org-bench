# Public reproduction protocol

This is a **separate public reproduction configuration**, with dedicated demonstration seeds. It is not a copy of the active private study dataset and does not replace the original registered protocol or results. Both seeds below are public, so generated cases are unsuitable as future blinded holdouts.

Its protocol hash is intentionally different from the original registered experiment's hash. Results must retain the hash of the protocol actually used; never relabel original results with this template hash. The retired original registration is preserved separately in the [registration archive](../archive/registrations/README.md), with its original metadata.

The corresponding public machine plan is [public machine plan](study_v6_plan.json). It locks the model, thinking setting, repetitions, concurrency, per-task limits and each stage's seed/task count. It is also different from the active/original study plan. Changing those values requires a new study identity, plan/protocol and output directories; do not overwrite frozen selection or run records.

## Question and design

Compare simplified coordination policies while controlling tools, public information and per-task resource limits. The primary question is whether the development-selected candidate improves hidden-test task success over compute-matched single-agent self-review. Additional review, context and allocation effects must not be called a pure topology effect.

All nine strategies receive the same public specification, starter program, three public examples, restricted-language contract and public executor. Thirty private cases per task are used only for final scoring. Private answers do not drive solver repair, audits, merge decisions or routing.

## Strategies

Development evaluates `plain_single`, `single_tool`, `single_self_review`, `hierarchy_tool`, `best_of_three`, `bazaar_tool`, `contract_team`, `adaptive_tools`, and `evidence_gated`.

- The plain single makes one proposal without repair.
- The strong tool single stops on passing actual public examples and otherwise repairs within its allowance.
- Self-review and contract-team controls match three required stages and 60%/10%/remaining output allocations; the former retains its full own history, while the latter gives the auditor only the public task and candidate. Actual input consumption can differ.
- The hierarchy uses a router, two isolated reports, integration and an optional public-failure repair.
- Best-of-three uses three complete isolated proposals, public ranking and fixed branch-id ties; it is not majority voting.
- Bazaar uses two isolated proposals and public-evidence selection.
- Adaptive routing retains the fixed public complexity threshold 25; it remains a template-proxy heuristic.
- Evidence-gated escalation uses a 60% initial proposal, at most one 20% public-failure repair, then a 10% independent audit and revision if failures persist or a frozen static-risk gate triggers. The gate checks at least six conditional markers in the public specification and either fewer than three candidate AST branches or fewer than 24 nonempty source lines. It is not a correctness oracle.

An auditor's claimed expected output is unverified and never becomes an external test expectation. The exact executable mechanisms and public ranking rules are defined in the exported registry and source.

## Model and limits

Reference reproduction settings: `deepseek-v4-pro`, non-thinking mode, requested/effective temperature 0.3; at most five logical model calls, 12000 cumulative output tokens and 32000 input-token preflight allowance per task. Actual usage and overages are retained. Routing, audits, reports, integration and repair count in the common allowance.

Outer concurrency is four task runs; internal stages are serial. Local task seeds do not seed provider sampling. Different models or settings are separate cohorts, not silently pooled replications.

Candidate programs run only through the immutable-input, restricted AST executor in its resource-limited process. This is not arbitrary Python execution or a universal hostile-code sandbox.

## Public development and confirmation seeds

- Development: seed **202611039901**, split `dev`, three tasks per family, nine total tasks, nine strategies, one repetition: **81 task runs**.
- Candidate set: `bazaar_tool`, `contract_team`, `adaptive_tools`, `evidence_gated`. Highest full hidden-task success count wins; ties use lower actual total tokens, then lexical name. All other strategies are controls.
- A selection can freeze only from a complete unique development grid with no infrastructure contamination and complete usage. Preserve result, source and protocol hashes.
- Reproduction confirmation: seed **202611039902**, split `holdout`, 20 tasks per family, 60 total tasks, one repetition and five arms: **300 task runs**.
- Confirmation arms: frozen candidate plus `single_tool`, `single_self_review`, `hierarchy_tool`, `best_of_three`.

The task sampler independently derives each task seed from its root seed/split/family/index, rather than advancing one shared finite rule-cycle phase. Rule support is still finite and repeated semantic combinations are possible; payloads and visibility streams remain separate. Same-template new seeds do not establish real-world distribution shift.

The runner defaults to `--plan docs/study_v6_plan.json`. Omitted `--seed` and `--per-family` are resolved from the selected stage. Explicit values must match the plan; arbitrary seed/count overrides are rejected. Model and resource arguments must also match the frozen plan. Manifests retain the plan hash, source/protocol hashes, order-preserving task hash and a credential-free provider endpoint identity.

## Registered endpoints

The primary quality comparison is candidate minus `single_self_review`: positive mean task-success difference, positive lower endpoint of the paired 95% task-bootstrap interval and two-sided exact task sign-permutation p<0.025 are all required.

The three secondary comparisons are against `single_tool`, `hierarchy_tool` and `best_of_three`, with Holm correction within that family at nominal alpha 0.025. Each also requires a positive mean difference and positive interval lower bound. A secondary success does not substitute for failure against the primary self-review control.

Tasks, not private cases or repeated API attempts, are the independent units. Per-family slices are exploratory; report paired counts and sample sizes without selecting favorable subgroups as new confirmation claims.

Token ratios, latency and observed Pareto points are **descriptive in this study**; this protocol has no efficiency-confirmation endpoint. Report input/output/cache usage, calls, public-pass/hidden-fail outcomes, audits and repairs. Unknown resource measurements remain unknown.

The nominal alpha allocation is 0.025+0.025. Bootstrap intervals have approximate coverage, not finite-sample exact guarantees. Completeness, unique expected cells, clean infrastructure, known usage and actual budget compliance are required for confirmation.

## Execution and publication

Model calls are explicit. Retry only an explicit HTTP429 rejection at most twice, with 3/10-second waits and every attempt logged. Ambiguous network failures are not automatically retried; prior unknown usage stays unknown. Latch dispatch closed after three consecutive final infrastructure errors. Normal candidate/test failures are retained as performance observations.

Do not change candidate, tools, prompts, executor, samples, budgets or decision thresholds after confirmation starts. Do not append samples until significant or combine an incomplete provider study with native-agent results. A provider-stop boundary takes precedence over completing a batch.

Publish this public protocol, curated aggregates and reviewed source/tests by allowlist. Raw runs, provider logs, active private cases, account information and native encryption/scoring material are excluded from the release tree. The author still chooses the project license.
