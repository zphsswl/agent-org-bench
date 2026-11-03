# Study status / 实验状态

**Completed and independently checked / 已完成并复核。**

| Stage / 阶段 | Design / 设计 | Status / 状态 |
|---|---|---|
| Development / 开发 | 9 tasks × 9 policies = 81 cells | Complete; exploratory |
| Selection / 选择 | One of four non-control candidates | `adaptive_tools` frozen |
| Confirmation / 独立确认 | 60 fresh tasks × 5 arms = 300 cells | Complete; all four candidate superiority gates not passed |

The primary control is `single_self_review`. Secondary comparisons against `single_tool`, `hierarchy_tool` and `best_of_three` are adjusted together with Holm. [Full results](results.md).

单体自检为主要质量参照；工具单体、层级和三候选择优为次要对照。开发选择不代表胜过全部基准，分族分析仍是探索。

## Evidence boundaries / 证据边界

The original confirmation attempt stopped after 49 cells because of transport failures and unknown usage. That attempt was invalidated. A replacement confirmation used fresh tasks with the same development selection, candidate, source, model, controls and hypotheses. None of the original 49 cells entered the final 300-cell result.

最初因网络与未知计量中断的49个单元全部排除；替代确认使用全新任务，没有改变已冻结的候选、代码或统计问题。恢复记录保留在[原始注册与审计材料](../archive/registrations/README.md)。

Earlier exploratory studies and the separate native pilot are outside this comparison. See the [archive](../archive/README.md) for provenance. No cross-study pooling is used.

## Follow-up / 后续

The proposed next study examines shared-draft review, correction, damage, observable triggers and stopping. Its offline preparation is not a completed model experiment or a new superiority claim. Retired analyzed tasks cannot be reused as a new blind confirmation.
