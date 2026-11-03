# v5: completed confirmation and limits

This is a curated aggregate result, not a dump of private tasks or provider logs.

## Setting

- One model: `deepseek-v4-pro`, non-thinking mode, requested temperature 0.3.
- Three synthetic code-repair families: document-version resolution, idempotent ledgers, and conditional configuration.
- Ninety independent confirmation tasks, 30 per family; one run per strategy and task.
- Shared public specifications, starter programs, public-example execution and declared per-task limits.
- Three frozen strategies, 270 complete unique cells; 937 successful API attempts, no unknown usage or actual per-task limit exceedances in the audited records.

## Quality

| Strategy | Versions | Ledgers | Config | Total |
| --- | ---: | ---: | ---: | ---: |
| `adaptive_tools` | 24/30 | 25/30 | 17/30 | 66/90 |
| `single_tool` | 22/30 | 9/30 | 13/30 | 44/90 |
| `hierarchy_tool` | 15/30 | 17/30 | 9/30 | 41/90 |

| Candidate minus baseline | Success difference | Marginal paired 95% interval | Holm-adjusted p |
| --- | ---: | --- | ---: |
| vs `single_tool` | +24.44 percentage points | [+13.33, +34.44] pp | 0.00005948 |
| vs `hierarchy_tool` | +27.78 percentage points | [+17.78, +38.89] pp | 0.00000930 |

Both preregistered quality comparisons passed the allocated Holm threshold of 0.025 and positive-interval checks. This supports a quality advantage under this particular model, task distribution, tool interface and implementation.

## Token efficiency did not pass

The observed total-token ratio against `single_tool` was 0.93644, with a paired 95% interval [0.80055, 1.09997]. Its upper bound did not meet the preregistered 0.85 threshold. Four task losses gave a one-sided 97.5% loss-probability upper bound of about 10.99%, above the 5pp margin. The baseline's observed success rate, 48.89%, also missed the predefined 50% usability gate.

Therefore the study did **not** confirm token savings, equal quality, epsilon-Pareto improvement, or monetary savings. Tokens are a resource proxy, not a provider bill.

## Attribution limits

The v5 route score is template-constant: versions 21, ledger 31, config 19. Threshold 25 sends only ledger tasks to `contract_team`; the other two families use the same implementation as `single_tool`, sampled independently. Earlier descriptions used 20/30/18 before the immutable-input wording was added; the routing decisions did not change.

Ledgers account for 16 of the 22 net additional correct tasks. Other families have net differences of +2 and +4 despite the same implementation, which cannot be attributed to different organizations.

`single_tool` stops on public success, while the contract team audits and revises even after public success. A compute-matched single-agent self-review control was absent. The gain can involve additional review, prompts, context independence and allocation rules; it is not an isolated proof that topology alone caused the improvement.

Bootstrap coverage is approximate. Nominal error allocation is not a finite-sample exact coverage guarantee. These results do not establish universal optimality, a novel general algorithm, real-repository generalization, or superiority over the official DSH persistent multi-task system.
