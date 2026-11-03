# Methods and comparison scope

## Mechanisms, frameworks and reproductions

The unit of comparison is an executable coordination policy: its information flow, public state, tool use, allocation, candidate selection and stopping behavior.

Names such as supervisor–worker, fixed DAG, blackboard, independent ensemble and audit team describe **simplified mechanism implementations** here. They are not official DSH, AutoGen, CrewAI, LangGraph, G-Designer or GPTSwarm reproductions. A framework can implement many different coordination graphs; a framework name is not itself the topology treatment.

An official integration or paper reproduction must separately document the upstream project, pinned revision, configuration, task/tool mapping and modifications. Unrun integrations remain unrun, rather than being inferred from a similar diagram.

## Controls

Keep the low-overhead, public-pass-then-stop single agent. Add compute-matched self-review, and compare with independent complete candidates selected using public evidence. These distinguish useful coordination from extra attempts, self-checking, information access or larger actual consumption.

Equal per-task upper limits are not equal actual consumption. All administrative calls, audits, integrations and repairs count. The router and workers must receive the same public task information and tool capabilities as the appropriate control.

## Public versus private evaluation

Solvers receive specifications, starter code, public examples and allowed-subset rules. Public feedback comes only from actual public execution. Model-proposed counterexamples or expected outputs are unverified hypotheses.

Final hidden evaluation is outside the solver loop. Passing public examples is not the same as passing the task. A task's hidden cases are within-task checks, not additional independent research samples.

A successful run must complete its declared organization policy within the allowed resources and pass every terminal case. An incumbent returned after an incomplete policy or budget stop is retained for best-effort diagnostics and does not replace the primary failed-run outcome. Thus the primary score measures successful delivery under the declared policy, rather than unrestricted function accuracy alone.

Generated Python is interpreted in a restricted AST language, with bounded execution processes and immutable-input checks. This is not arbitrary Python execution or a general production security sandbox.

## Generation and generalization

Rules depend on seed, split, family and index. The current generator uses finite rule cycles: 96 version combinations, 64 ledger combinations and 128 configuration combinations. Seeds change the rule phase and payloads; a new seed is not an unrestricted new task family.

The v5 audited development/confirmation rule sets did differ. Generation order did not alter regenerated tasks, and isolated candidate executions did not share module state. These checks do not replace new templates, real repositories or out-of-distribution evaluation.

## Decisions

Freeze candidate selection on development data before opening confirmation results. Use paired task-level analyses, preserve repetitions inside each task cluster and adjust the declared comparison family. Publish incomplete and invalidated outcomes separately.

Quality superiority, noninferiority and resource savings are different hypotheses. Failure to find a quality difference does not prove equal quality. A cheaper point estimate does not prove savings. Observed Pareto points remain descriptive unless the specified uncertainty and quality gates pass.

Native-agent and API backends have separate models, context wrappers and observable resources. Their outcomes are not pooled; unknown native usage remains unknown.

## What an agent identity means in this implementation

The API provider is stateless between calls. A logical single solver is implemented by supplying its complete earlier messages and actual public feedback as text context. An independent worker receives a restricted fresh context. The interventions also include explicit stage instructions; this is not a clean manipulation of a human-like identity or a proof that model errors become statistically independent.

See the [architecture catalog](architecture_catalog.md) for executable stages, context access, acceptance and stopping rules for every current mechanism.
