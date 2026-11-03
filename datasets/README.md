# Retired public benchmark tasks / 已退休的公开任务

These are the exact public specifications, starter programs and examples supplied in the completed studies, projected to public fields only:

- [v5 confirmation: 90 tasks](v5/tasks.public.json)
- [v6r1 confirmation: 60 tasks](v6r1/tasks.public.json)
- [Three independent demonstration tasks](../examples/public_demo_tasks.json)

Each task contains its complete `public.spec`, fixed semantic `public.rules`, deliberately incorrect `public.starter_source`, three public examples and the permitted Python subset. `prompt` is the original model-facing public prompt. Mapping insertion order is preserved because configuration patches can depend on it.

Only public input and expected-output examples are included. Hidden case payloads, final model solutions, provider logs and account records are excluded. The public field projection has its own file hash; it is not the full public-plus-private suite hash from the original manifest.

The generator and retired protocol seeds permit reconstructing old reference cases. All released tasks are permanently retired from future blind confirmation. New trials require new data and a separately frozen protocol. New seeds from the same three finite templates are not real-world out-of-distribution evaluation.

具体任务解释见[任务卡与示例](../docs/task_examples.md)。这些数据用于复查已完成研究，不能再作为V7或新策略的最终盲测。
