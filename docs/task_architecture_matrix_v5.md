# v5任务—组织矩阵与探索性分层

研究日期：2026-11-03（客户端上下文）。使用已经完整结束的90道确认题×3组织、共270个唯一运行。这里只做事后探索和机制解释，不增设确认检验、不修改原始评分、候选、预算或路由阈值，也不依据已看过的holdout选择下一轮阈值。

原decision.json记录总体质量相对两个冻结对照的确认通过、效率确认未通过；这些是既定主分析的结论。分族、规则单值和完整签名的差异不自动继承总体确认地位。分层重复、相关且多重，本文不另算p值或挑选显著子组。完整可公开汇总见[task_breakdown.json](../results/v5/task_breakdown.json)。

## 任务—组织主矩阵

| 任务族 | 每组任务 | single全对 | adaptive全对 | hierarchy全对 | adaptive实际实现 | 冻结复杂度 |
|---|---:|---:|---:|---:|---|---:|
| `code_config` | 30 | 13/30 | 17/30 | 9/30 | `single_tool` | 19 |
| `code_ledger` | 30 | 9/30 | 25/30 | 17/30 | `contract_team` | 31 |
| `code_versions` | 30 | 22/30 | 24/30 | 15/30 | `single_tool` | 21 |

| 任务族 / 组织 | 输入Token | 输出Token | 总Token | 模型调用 | 未知usage运行 |
|---|---:|---:|---:|---:|---:|
| `code_config` / `single_tool` | 328,033 | 107,909 | 435,942 | 103 | 0 |
| `code_config` / `adaptive_tools` | 276,019 | 95,386 | 371,405 | 89 | 0 |
| `code_config` / `hierarchy_tool` | 415,930 | 132,587 | 548,517 | 142 | 0 |
| `code_ledger` / `single_tool` | 343,225 | 66,434 | 409,659 | 103 | 0 |
| `code_ledger` / `adaptive_tools` | 359,966 | 77,375 | 437,341 | 98 | 0 |
| `code_ledger` / `hierarchy_tool` | 418,795 | 84,670 | 503,465 | 133 | 0 |
| `code_versions` / `single_tool` | 217,440 | 63,910 | 281,350 | 68 | 0 |
| `code_versions` / `adaptive_tools` | 187,840 | 58,736 | 246,576 | 59 | 0 |
| `code_versions` / `hierarchy_tool` | 454,826 | 104,458 | 559,284 | 142 | 0 |

账本族中，传统层级组17/30高于强单体9/30，说明不能把层级开销一概解释为无收益；本候选25/30仍高于层级。版本与配置族，层级分别为15/30、9/30，低于单体22/30、13/30。即便总体候选占优，传统层级在特定结构下也确有比强单体更好的观察结果。

进一步的反例：公开配置规则merge=preserve的5题里，hierarchy为1/5、adaptive为0/5、single为1/5；全体还有3道题只有hierarchy成功，另外两组均失败。小组极小且事后重叠，不能据此确认该规则适合层级，但这些失败反例不能从公开矩阵中删去。

## 同算法重复运行与实质处理要分开

版本族和配置族的adaptive实际调用的就是single_tool同一代码路径，而非另一种拓扑。以下配对差是同算法重新独立请求的波动，可能含供应商采样和服务波动，不能归于路由改进。账本才采用contract_team，与single构成实质组织处理；其差异仍同时含采样波动，不能把观察净差当纯因果效应。

| 配对分块：adaptive减single | 题目 | adaptive独成 | single独成 | 双成功 | 双失败 | 成功率差 | 初始model提示完全相同 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 同single实现：版本+配置 | 60 | 10 | 4 | 31 | 15 | +10.0% | 60/60 |
| 团队处理：账本 | 30 | 16 | 0 | 9 | 5 | +53.3% | 0/30 |

总体66比44的净多22次成功中，6次净差来自60道同single实现的重复运行，16次来自30道账本团队处理。这个加法只是观察分解，不是“组织贡献百分比”。尤其不能将版本+配置的净多6次解释为adaptive更会选择组织。

资源也需要同样分解：版本+配置这60道相同single算法的重复运行，adaptive标签下总Token观察少13.85%；账本的团队处理反而多6.76%。不能将总体观察到少用Token一并归因于团队组织；不同成功/失败修复轨迹也会改变同算法的实际消耗。

冻结特征仅来自公开spec/rules的叶子数和特定条件/依赖词计数。实际公开题面与trace显示版本、账本、配置模板分别恒定为21、31、19。冻结协议文字写20、30、18，少计了统一不可变契约中一个must条件词；去除该固定后缀后逐题重算与协议数字一致。两组数字相对阈值25的路由完全相同；这里仅记录文案偏差，没有修改原协议、实现或阈值。该特征在模板内恒定，没有识别同模板内题目难度。完整特征值分层已导出，未搜索替代阈值。

## 公开规则单值分层（全量展示，非确认）

同一道题会出现在多个规则单值组中，不能把这些n相加。小组不均衡，部分规则全固定；差异可能混入其他共同变化规则。以下全部展示而非只挑候选有利的组。

| 任务族 | 公开规则=值 | n | single全对 | adaptive全对 | hierarchy全对 | hierarchy减single配对净差 |
|---|---|---:|---:|---:|---:|---:|
| `code_config` | `condition_context="live"` | 16 | 11 | 13 | 6 | -31.2% |
| `code_config` | `condition_context="snapshot"` | 14 | 2 | 4 | 3 | +7.1% |
| `code_config` | `dependencies="revisit"` | 15 | 7 | 8 | 7 | +0.0% |
| `code_config` | `dependencies="single_pass"` | 15 | 6 | 9 | 2 | -26.7% |
| `code_config` | `keys="lower"` | 30 | 13 | 17 | 9 | -13.3% |
| `code_config` | `merge="overwrite"` | 25 | 12 | 17 | 8 | -16.0% |
| `code_config` | `merge="preserve"` | 5 | 1 | 0 | 1 | +0.0% |
| `code_config` | `null="delete"` | 14 | 7 | 7 | 5 | -14.3% |
| `code_config` | `null="literal"` | 16 | 6 | 10 | 4 | -12.5% |
| `code_config` | `priority_order="ascending"` | 15 | 10 | 11 | 6 | -26.7% |
| `code_config` | `priority_order="descending"` | 15 | 3 | 6 | 3 | +0.0% |
| `code_config` | `tie="id_lex"` | 14 | 5 | 8 | 2 | -21.4% |
| `code_config` | `tie="input"` | 16 | 8 | 9 | 7 | -6.2% |
| `code_ledger` | `bonus_comparison="ge"` | 6 | 1 | 6 | 2 | +16.7% |
| `code_ledger` | `bonus_comparison="gt"` | 24 | 8 | 19 | 15 | +29.2% |
| `code_ledger` | `cancel="forward"` | 15 | 0 | 10 | 5 | +33.3% |
| `code_ledger` | `cancel="global"` | 15 | 9 | 15 | 12 | +20.0% |
| `code_ledger` | `count_noop_freeze=false` | 14 | 5 | 12 | 8 | +21.4% |
| `code_ledger` | `count_noop_freeze=true` | 16 | 4 | 13 | 9 | +31.2% |
| `code_ledger` | `credit_frozen=false` | 16 | 5 | 13 | 9 | +25.0% |
| `code_ledger` | `credit_frozen=true` | 14 | 4 | 12 | 8 | +28.6% |
| `code_ledger` | `dedup="first_applied"` | 14 | 3 | 13 | 9 | +42.9% |
| `code_ledger` | `dedup="first_seen"` | 16 | 6 | 12 | 8 | +12.5% |
| `code_ledger` | `transfer_requires_unfrozen_destination=false` | 14 | 2 | 12 | 7 | +35.7% |
| `code_ledger` | `transfer_requires_unfrozen_destination=true` | 16 | 7 | 13 | 10 | +18.8% |
| `code_versions` | `authority="higher"` | 15 | 13 | 13 | 11 | -13.3% |
| `code_versions` | `authority="lower"` | 15 | 9 | 11 | 4 | -33.3% |
| `code_versions` | `keys="case_sensitive"` | 14 | 12 | 11 | 8 | -28.6% |
| `code_versions` | `keys="lower"` | 16 | 10 | 13 | 7 | -18.8% |
| `code_versions` | `priority="authority_then_time"` | 15 | 11 | 12 | 6 | -33.3% |
| `code_versions` | `priority="time_then_authority"` | 15 | 11 | 12 | 9 | -13.3% |
| `code_versions` | `qualified_retractions=false` | 9 | 9 | 9 | 5 | -44.4% |
| `code_versions` | `qualified_retractions=true` | 21 | 13 | 15 | 10 | -14.3% |
| `code_versions` | `retraction_scope="global"` | 9 | 9 | 9 | 5 | -44.4% |
| `code_versions` | `retraction_scope="not_after_retractor"` | 21 | 13 | 15 | 10 | -14.3% |
| `code_versions` | `tie="first"` | 13 | 10 | 13 | 6 | -30.8% |
| `code_versions` | `tie="id_lex"` | 8 | 5 | 4 | 4 | -12.5% |
| `code_versions` | `tie="last"` | 9 | 7 | 7 | 5 | -22.2% |

完整公开语义签名共90组，组内任务数分布为`{1: 90}`。签名是公开规则JSON的固定指纹，不是事后按答错类型划分。绝大部分或全部为单题组，只能定位一个已观察实例，不能支持某签名下组织胜出的总体结论；详列质量、资源和配对四格计数于JSON。

## 失败分类与预算

分类使用已经落盘的执行状态、最终公开反馈及调用trace，不重新运行隐藏测试。公开未通过与公开通过但隐藏失败分开；模型单次max_tokens终止仅是辅助标记，不能自动重命名为整题预算错误。

| 任务族 / 组织 | 公测未过 | 公测过但hidden未全过 | 预算停止 | 基础设施错误 | 曾有max_tokens终止的运行 |
|---|---:|---:|---:|---:|---:|
| `code_config` / `single_tool` | 17 | 0 | 0 | 0 | 0 |
| `code_config` / `adaptive_tools` | 13 | 0 | 0 | 0 | 0 |
| `code_config` / `hierarchy_tool` | 20 | 1 | 0 | 0 | 0 |
| `code_ledger` / `single_tool` | 16 | 5 | 0 | 0 | 0 |
| `code_ledger` / `adaptive_tools` | 2 | 3 | 0 | 0 | 17 |
| `code_ledger` / `hierarchy_tool` | 12 | 1 | 0 | 0 | 0 |
| `code_versions` / `single_tool` | 8 | 0 | 0 | 0 | 0 |
| `code_versions` / `adaptive_tools` | 4 | 2 | 0 | 0 | 0 |
| `code_versions` / `hierarchy_tool` | 15 | 0 | 0 | 0 | 1 |

资源表为实际供应商usage。未知计量单列，不补成0。错误细分中的输入变异、AST语法/子集、运行期错误、输出不匹配与资源限制来自真实公开反馈；同一运行可先失败再修好，因此“曾出现”计数可重叠，不能等同最终失败总数。隐藏only错误只说最终未全过，不根据源码猜测隐藏具体根因。

## 后续实验与公开发布边界

后续若检验账本审计收益，应在新开发/新确认任务中预先固定审计、同等额外自检、独立完整候选等机制消融，并保留相同single算法多次重复来量化采样差。不能用已经看过的这90题选择路由阈值，再将同一数据宣称为新确认。规则单值分层也不能代替难度分类器或证明跨模板泛化。

本JSON面向GitHub只包含公共规则派生分层、汇总质量/usage/调用/失败计数与源指纹；不含候选源码、提示文本、私有用例、API日志、请求UUID或凭据。原始评分和既定decision未作任何修改。

复编译：`python analysis/v6_task_breakdown.py`。

自检：270单元完整唯一，公开路由特征与trace一致，冻结阈值均25，未发现指纹/路由警告。
