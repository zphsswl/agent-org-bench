# Study status and configuration inventory

## Evidence ledger

| Study | Status | Interpretation |
| --- | --- | --- |
| Early reasoning-task studies | Historical; settings included severe floors | Diagnostics and historical results, not a v5-compatible ranking |
| Rate-limited or interrupted batches | Invalidated/incomplete | Infrastructure evidence, not architecture superiority |
| Pre-isolation code-task development | Debug only | Superseded before valid confirmation |
| v5 code-task confirmation | Completed and audited | Scoped quality improvement; token efficiency not confirmed |
| Native single-agent pilot | Separate exploratory backend | Small-sample feasibility/ceiling observation, not an API-comparable arm |
| v6 | Completed; audited original and recomputed decisions agree | See [bilingual results](results-v6.md); primary and secondary declarations are separate |

The research inventory includes **17 historical configurations and four added v6 configurations**. These are versioned research records, not 21 architectures evaluated under one valid common benchmark. Repeated or renamed mechanisms must not be double-counted as independent evidence.

## v6 design

- Nine strategies on nine development tasks: 81 task runs.
- Exactly one candidate selected and frozen using development data.
- Sixty fresh confirmation tasks with five arms: 300 task runs.
- Confirmation arms: candidate, `single_tool`, `single_self_review`, `hierarchy_tool`, `best_of_three`.
- Primary control: compute-matched `single_self_review`.
- Secondary control comparisons: the other three baselines, adjusted together with Holm under the frozen protocol.

The implementation registry and frozen protocol define the exact nine strategies, stage budgets, candidate rule and statistical thresholds. Do not infer them from labels alone or choose a favorable comparison after seeing confirmation.

| Implementation | v6 role |
| --- | --- |
| `plain_single` | One proposal, no repair; descriptive development control |
| `single_tool` | Public-pass early stop and failure-triggered repair; confirmation control |
| `single_self_review` | Compute-matched self-review; primary confirmation control |
| `hierarchy_tool` | Simplified supervisor–worker; secondary confirmation control |
| `best_of_three` | Independent proposals selected by public evidence; secondary confirmation control |
| `bazaar_tool` | Two isolated complete proposals; selectable candidate |
| `contract_team` | Initial code, independent audit, revision; selectable candidate |
| `adaptive_tools` | Frozen template-proxy route; selectable candidate |
| `evidence_gated` | Public-failure/static-risk-triggered escalation; selectable candidate |

The public [v6 reproduction protocol](protocol_v6.md) uses dedicated demonstration seeds, not the original or active study seed values.

The prior roadmap's larger sample suggestions are proposals, not the final v6 registration. Do not present its suggested counts as executed v6 runs.

## Updating this page

Change a status only from an audited manifest and complete decision artifact. A development leader is not a confirmation winner. Failed or invalidated studies stay visible, and old holdouts become descriptive data once used to design a new strategy.

<!-- BEGIN V6 FINALIZATION -->

## Finalized local v6 state

State: **completed**. Development: 81/81; confirmation: 300/300. The declared primary and three secondary comparisons are reported individually. A null result is not equivalence. Previously valid v5 evidence is unchanged. [Details](results-v6.md).

<!-- END V6 FINALIZATION -->
