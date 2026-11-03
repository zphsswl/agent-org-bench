# v6r1：传输中断后的独立确认恢复

本修订在首次v6r1模型调用前登记。继承原v6的任务定义、求解源码、工具、候选、对照、模型、模式、资源上限、外层4并发及全部统计方法。原协议为docs/protocol_v6.md，原机器计划为docs/study_v6_plan.json；精确哈希及继承链记录在docs/v6r1_recovery_amendment.json。不是重新调参或重新选择候选。

原开发runs/tools_dev_v6已完成9题×9实现=81cells，237/237 API成功，无未知usage。沿用其原始结果与原始清单，不伪造为新开发。原选择为adaptive_tools，开发8/9；主要对照single_self_review为9/9，不能称候选是所有开发组第一。原选择文件完整保留。

原确认runs/tools_holdout_v6在49/300处因4次ConnectionResetError/URLError、usage未知而自动熔断，已经失效，不恢复失败单元，不把49行并入本轮质量结果。随后只读HTTPS与认证账户查询恢复可达，无HTTP402；不能由此声称已定位或修复上游重置根因。

本轮只将确认seed换为**2026110308**，split holdout，每族20题共60题；adaptive_tools、single_tool、single_self_review、hierarchy_tool、best_of_three各一次，共300cells。采用逐题独立SHA256派生种子和保序suite_hash。仍可能重复有限语义组合；不是现实仓库的分布外验证。

模型deepseek-v4-pro、thinking disabled、temperature0.3、每cell最多5calls、12000output/32000input估算预检，实际用量全部保留。源码必须仍为cf1437bfcd01b5fab047bb54dc46dfdb69bad76fac0475fb1523407adb4de47f。不得更改提示、阶段配额、路由、baseline、验收、统计阈值或利用原确认质量来选择策略。

主比较仍是候选对single_self_review，双侧精确配对p<.025、正平均差且95%配对bootstrap下界>0；次要三比较仍为独立Holm家族alpha=.025，分别判定。成本比仅描述，不设置效率确认门。所有完整性、未知计量、基础设施与真实超限守卫继承。预算内耗尽属于正常性能失败，不能当基础设施污染或任意剔除。

新机器计划为docs/study_v6r1_plan.json。新选择记录selection_v6r1.json保留原candidate/architectures/ranking/development_results_hash，显式绑定原selection及修订哈希，重绑定新protocol/plan；原开发清单的旧哈希不修改。报告与导出须验证该继承链，不得仅把开发protocol/plan改成新值来伪装一致。

若恢复确认再次发生基础设施污染，保留并关闭确认声明，不反复追加至显著。额度耗尽不再调用DeepSeek或请求充值；任何原生实验必须单独注册和计量，不能补入API单元。本地发布仍须净化，不发布认证、原始日志、trace、答案或活跃隐藏案例。
