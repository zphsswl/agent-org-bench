# Known limitations / 已知限制

This initial release preserves the measured implementation. Its `orgbench/*.py` source hash is `cf1437bfcd01b5fab047bb54dc46dfdb69bad76fac0475fb1523407adb4de47f`; the limitations below do not silently change that implementation or its archived results.

本次首次发布保留已经测量的源码和结果。以下限制不是新发现的架构胜出证据，也不通过修改冻结源码来追改旧实验。

## Provider usage contract / 供应商用量契约

The frozen client is intended for the tested Anthropic-compatible adapter. It **does not fail closed on every missing or malformed usage field**: [provider.py:138](../orgbench/provider.py#L138) substitutes an empty usage object, [provider.py:143](../orgbench/provider.py#L143) and [provider.py:154](../orgbench/provider.py#L154) normalize missing/invalid token values to zero, and the response can still be recorded as successful. A successful transport response alone therefore does not prove complete usage measurement for an arbitrary compatible endpoint.

冻结客户端不会对所有缺失或格式错误的usage字段拒绝计量：缺失/非法Token值可能被规范化为0，然后仍返回成功。不要将其解释为“未知用量被可靠保留为未知”，也不要未经验证就把新供应商适配器用于资源优势结论。

For the archived successful cohorts, a separate read-only inspection by the release owner found positive integer **parsed result** input/output counts for all v5 development 253 calls, v5 confirmation 937 calls, v6 development 237 calls and v6r1 confirmation 1,031 calls. The original raw usage objects were not retained, so this inspection cannot retrospectively prove the original type/presence of every raw subfield. This is an audit boundary, not evidence that an observed cohort had missing usage. Future versions should validate required usage fields strictly or mark usage unknown before new measurements.

发布负责人对有效批次的本地已解析记录做了单独只读检查：v5开发253次、v5确认937次、v6开发237次、v6r1确认1,031次，input/output结果均为正整数。原始raw usage对象未保存，因此不能据此追溯证明每个原生子字段都存在且本来就是整数。后续版本应在新实验前加入严格字段校验或未知计量标记；这份发布不伪称旧客户端已经做到。

## One process per output directory / 每个输出目录只允许一个进程

The runner serializes result writes inside one process, but has **no cross-process experiment lock**. The manifest check, completed-cell read and append writer occur separately: [study_v6.py:167](../orgbench/study_v6.py#L167), [study_v6.py:184](../orgbench/study_v6.py#L184), [study_v6.py:243](../orgbench/study_v6.py#L243).

Only one CLI process may own an `--out` directory at a time. This includes live execution, `--prepare-only`, `--select-only`, analysis that writes run artifacts, and resumption. Different experiments must use different directories. Do not start a second process against the same output directory while the first is active: it can duplicate paid work, append duplicate cells or race on metadata. The duplicate-grid guards reject contaminated confirmation; they do not prevent the duplicate API spending.

同一个`--out`目录只能由一个CLI进程持有，包括正式运行、准备、选择、会写运行产物的分析和恢复。不要在运行中对同一目录启动另一个prepare/select/runner。重复网格守卫能拒绝受污染的确认，但不能防止已经发生的重复计费。

## Resource bounds / 资源边界

Input allowance enforcement is a conservative estimate before a request plus observed usage checks afterwards, not an exact provider-tokenizer hard cap: [architectures.py:109](../orgbench/architectures.py#L109). A request can be charged before a reported actual overrun is detected. Output, call and isolated evaluator limits are separate controls. Equal limits do not imply equal actual consumption.

输入限制是调用前估算、调用后核对，不是精确分词器硬上限。API可能已计费后才发现实际超限。受限AST子进程的内存、时间和IO边界是执行防御措施，不是运行任意恶意Python的生产级安全沙箱。

## Worker isolation / Worker隔离

The API solver receives public problem text and real public feedback, while hidden grading is performed outside the solver loop. This does not make a broadly exposed repository safe for an autonomous filesystem-capable worker. A worker must not receive bare access to private cases, reference implementations, research-agent context, archived answers or active reconstructible holdout seeds. Use public-only packets and explicitly restricted tools; a shared filesystem identity is not adversarial access control.

API提示与隐藏判分的分离，不等于可以把整个研究目录直接交给具有文件工具的Worker。可信参考代码、私有题、旧答案与活跃确认材料必须留在其可读范围之外；共享文件系统身份不能当作安全隔离证明。公开演示集和已退休数据也不能再充当新策略的最终盲测。

## Evidence scope / 证据范围

- The measured policies use one hosted model alias and three finite synthetic code-task families in a restricted AST language. Official DSH/AutoGen reproductions, real-repository performance, long-lived asynchronous workloads and cross-model transfer are not established here.
- Task seeds reproduce generated tasks, not provider sampling or immutable model weights. The source/archive hashes do not pin hosted model internals.
- Nine development tasks are exploratory; 20 tasks per confirmation family do not establish task-specific winners. The v5 and v6r1 cohorts, and the separate native pilot, are not pooled.
- V6r1 confirmed none of the new router's four preregistered superiority comparisons. Non-significance is not equivalence/noninferiority. Its token ratios are descriptive, not equal-quality efficiency claims.
- [analyze_public_results.py](../analysis/analyze_public_results.py) replays arithmetic on released outcomes. It does not independently regrade original candidate programs or prove the original private grader's validity.

以上边界必须与正结果和负结果一起保留，不能把受限合成任务上的观察扩大为通用组织最优性。
