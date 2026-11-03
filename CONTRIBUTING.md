# Contributing

Start with [methods](docs/methods.md), [study status](docs/study-status.md), and [data policy](docs/data-policy.md).

## Local validation

Python 3.11 or newer, standard-library core:

```bash
python -m unittest discover -s tests
python -m orgbench.study_v6 --help
```

These commands must stay offline. Tests should use deterministic fixtures and mock provider responses. Do not require account credentials, a live model, matplotlib, or native-pilot cryptography in the main test suite.

## Changing a mechanism

Document its actual message graph, visible state, stage allowances, public-tool access, merge rules and stopping conditions. Count routing, auditing, integration and repairs in the same per-task allowance. Calling a component a manager, market or community does not by itself introduce a new mechanism.

When adding an agent strategy, include an appropriate single-agent or independent-sampling control. In particular, distinguish organization effects from additional self-review or a larger effective compute allowance.

Do not promote an auditor's proposed expected value into a test oracle. Private evaluation must remain outside the solver boundary.

## Experimental changes

Keep completed protocols and results immutable. New prompts, generators, allocation rules or evaluation semantics require a new version and new confirmation tasks. Development data selects a candidate; confirmation data must not select its replacement.

Report failures, missing cells, unknown usage and infrastructure problems. Never delete adverse runs to improve a ranking. Label approximate intervals and descriptive analyses accurately.

## Pull requests

Explain the problem, resulting behavior, validation performed and limitations. For research changes, include the new protocol and relevant mechanism controls. Do not claim a general improvement from a single development seed or a framework-name substitution.

Do not commit raw experiments, provider logs, credentials, account information, active private cases or native-pilot encryption material. Review staged files against the [release checklist](docs/release-checklist.md), including files already tracked before a gitignore rule existed.

The author has not selected a license; follow [LICENSE-NOTICE.md](LICENSE-NOTICE.md) rather than inventing a license or ownership claim.
