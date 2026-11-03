# 文献与组织机制核验

核验日期：2026-11-02。核验对象是《想法01.md》中的引用与研究前提；只采用论文、作者、出版社或官方项目资料。本文不修改原始想法文件。

## 核验结果

| 条目 | 状态与应作的限定 | 原始来源 |
| --- | --- | --- |
| DSH Super-agent | 已确认是用户给出的 `deepseek-ai/dsh-superagent-prototype`。官方 README 明示它是研究原型，与内部版本、设计文章不完全一致。其工作单位是持续维护的 Ticket、独立 Worker 会话与工作目录，并通过事件订阅承接后续消息。它首先解决多项工作持续推进与人类注意力问题。 | [官方 README](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/main/README.md)、[架构](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/main/docs/007-architecture.md) |
| Google 的 180 配置研究 | 引用有依据，但存在版本变化。2026-01-28 官方博客及早期论文使用 180 配置；2026-04-08 的 arXiv v3 改为 260 配置、6 个基准。旧版数字和新版统计值不可混合使用。它支持“结构需匹配任务”，不能证明某一社会组织普遍最优。 | [官方博客](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/)、[论文 v3](https://arxiv.org/abs/2512.08296v3) |
| G-Designer | 已核实 ICML 2025 / PMLR 267。其机制是任务条件下的通信图生成与优化，不是给 Agent 写不同职位名称。摘要中的性能提升受模型、基准与对照条件约束。 | [论文正式页](https://proceedings.mlr.press/v267/zhang25cu.html) |
| Blackboard Multi-Agent | 已核实 Google 官方 2025 论文。原系统仍由中央 Agent 在黑板发布请求，分区 Agent 自愿响应；因此黑板不必等于完全去中心化。数据湖发现任务的结果不能直接外推到编码与数学推理。 | [官方论文页](https://research.google/pubs/blackboard-multi-agent-systems-for-information-discovery-in-data-science/)、[arXiv](https://arxiv.org/abs/2510.01285) |
| Agora | 原文 ACL 链接有效，标题与作者匹配，不属于杜撰引文。2026 Findings EMNLP 正式摘要强调校准后的能力竞标，并称在匹配候选池下改善或保持竞争力。未经校准的自报置信度竞标，不应称为 Agora 复现，也不能预设机制天然诚实。 | [正式论文页](https://aclanthology.org/2026.findings-emnlp.1237/)、[arXiv v2](https://arxiv.org/abs/2607.09600v2) |
| GPTSwarm | 已核实 ICML 2024。节点是计算或模型调用，边是信息流，包含节点提示与边连接优化。只实现固定黑板不能称复现其优化算法。 | [正式论文页](https://proceedings.mlr.press/v235/zhuge24a.html) |
| ADAS / MASS | ADAS 的 Meta Agent Search 通过代码搜索系统；MASS 联合研究提示与拓扑优化。它们说明自动组织设计已存在先行工作。手写特征路由只是本项目可检验的原型，不是新的自动发现算法。 | [ADAS](https://arxiv.org/abs/2408.08435)、[MASS](https://arxiv.org/abs/2502.02533) |
| Debate or Vote | 已核实 NeurIPS 2025。其七个 NLP 基准中的投票对照说明：多次独立采样本身可能解释不少收益。论文中的随机过程结论依赖建模假设，不能解释为所有辩论必然无效。 | [正式论文页](https://papers.nips.cc/paper_files/paper/2025/hash/934252acd87f254d5d4672fbde283bd2-Abstract-Conference.html) |

本轮若使用“Router–Worker 风格简化对照”，只能比较本地实现的任务内信息流。没有运行官方 DSH 原型，也没有覆盖持久化、多任务突发到达、订阅后续事件与人类注意力消耗，因此不能据此宣布“超过 DSH”。

## 从组织理论到可执行规则

下表中的 Agent 机制是本项目的设计推导，不是原著已证明的 LLM 结论。它们只有落实为调度、读写权限、合并条件与资源规则，才能与普通角色提示词区分。

| 组织来源 | 可实现机制 | 可证伪的预测 | 必要消融或反例 |
| --- | --- | --- | --- |
| Smith，Contract Net Protocol（1980） | 发布任务及准入条件；候选节点报价；局部授予限时执行权；超时重新发布。能力记录只由开发/训练阶段的外部验证更新，测试前冻结。 | 存在真实能力差异与负载差异时，比固定派工减少错配。 | 同模型同工具同提示的同质节点可能没有可竞标的信息优势；竞标通信可能只增加成本。 |
| Raymond，《大教堂与集市》 | 隔离分支探索；产出可执行候选；统一公开测试、独立审查、明确合并规则；保存被拒候选。 | 候选路线有差异且易于检验时，提高解决率。 | 与等预算独立多次采样、best-of-N、简单多数投票比较，区分“开放协作”和“多试几次”。 |
| Ostrom，《公共事务的治理之道》及多中心治理 | 对工作板、工具额度、可修改模块设局部边界与配额；局部团队自治；跨边界写入需协议；监测违规、撤销租约；冲突只在必要时升级。 | 共享资源竞争与跨模块冲突下，减少重复执行与争用。 | 单一小任务没有资源治理压力，机制可能得不偿失；需加入共享工具/文件冲突任务才能检验。 |
| Beer，《Brain of the Firm》 | 执行与监测分离；监测器读取延迟、停滞、错误和队列长度；依据预先固定阈值扩缩并行度、触发修复或降为单体；监测调用计费。 | 长任务、突发负载与节点故障下改善尾延迟和恢复率。 | 无故障静态题集不能证明可生存性；监测器也可能成为瓶颈或错误源。 |
| Dorigo 等，Ant System（1996） | 只给已验证路径增加共享信号；信号随时间衰减；保留探索概率；限制同一线索的并发追踪。 | 搜索空间可分、反馈可靠时减少重复探索。 | 同源错误会被正反馈放大；单纯共享 JSON 板不等于实现蚁群优化。 |
| 独立审查与制衡 | 提案和否决使用不同信息路径；异议必须带反例或可执行失败证据；保留少数候选；由固定证据规则处理冲突。 | 相关错误、虚假共识较多时减少错误传播。 | 同模型不同身份不保证独立；与等预算自检比较，且不能把同一模型赞同当外部验证。 |

对应原始材料：[Smith 作者提供的 1980 论文](https://www.reidgsmith.com/The_Contract_Net_Protocol_Dec-1980.pdf)、[Raymond 原文](https://firstmonday.org/ojs/index.php/fm/article/view/578)、[Ostrom Workshop 对原书与设计原则的说明](https://www.ostrom.indiana.edu/courses-teaching/teaching-tools/ostrom-design/index.html)、[Beer 出版社书目](https://uat.store.wiley.com/en-se/shop/general-introductory-business-management/brain-of-the-firm-2nd-edition-p-9780471948391)、[Dorigo 等论文原文](https://www.cs.put.poznan.pl/mmachowiak/ok/ACOtsp.pdf)。Beer 本次仅核验出版社书目信息及简介，未逐章核验原书；上述监测器是研究设计提案，不称完整 VSM 实现。

## 当前优先级

先比较单体、迭代单体、层级、固定 DAG、黑板、独立分叉、原型市场和手写混合路由；这些机制的独立增益可以在小型可程序判分任务上先检验。多中心治理与控制论适合下一轮有资源争用、故障和事件流的试验，不应仅换一个名字加入同一静态题集。

有价值的成果可以是“在某一任务族、同一模型及资源约束下更有效的机制”，也可以是“哪些组织成本没有转化成质量收益”。现有文献和本轮实验都不能支持“人类公司形式必然限制 Agent 上限”，也不能证明一个组织架构普遍最优。
