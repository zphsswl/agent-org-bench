# Release checklist

This directory is a publication staging tree. Source and tests are populated by the reviewed exporter after the experiment implementation is frozen; do not publish a documentation-only tree as a runnable benchmark.

Before release:

1. Export frozen source and offline tests by allowlist. Verify `orgbench/study_v6.py` and nonempty tests exist; a zero-test discovery result is not validation.
2. Check code/protocol/data revision metadata and distinguish completed evidence from plans. Keep the v5 aggregate and the final v6 protocol/results separate.
   Preserve the public reproduction `docs/protocol_v6.md`; its hash differs from the original registration. A retired original protocol, if approved, uses a distinct `protocol_v6_original.md` name. Historical source snapshots remain outside the current package namespace.
   Also preserve `docs/study_v6_plan.json` with public reproduction seeds; never overwrite it with the active root study plan. Verify the two public stage counts and runtime settings agree with the public protocol.
3. Run `python -m unittest discover -s tests` and `python -m orgbench.study_v6 --help` from this directory. Confirm no credentials or live requests are needed.
4. Validate `pyproject.toml` and both README language versions. Check relative links after the exporter has populated referenced files.
5. Review every staged path/content for credentials, raw runs, private cases, account information, local absolute paths and native encryption/scoring material. Gitignore alone is not sufficient.
6. Publish only the dedicated public reproduction seed/examples, not active confirmation material or reconstructible active seeds.
7. Check CI stays offline and read-only. The main matrix must not install the optional native-pilot cryptography dependency or require account secrets.
8. Keep official integrations distinct from simplified mechanisms; do not call a renamed local pattern a framework/paper reproduction.
9. Leave licensing explicitly pending until the author chooses it. Do not publish a package with an invented license or false ownership metadata.
10. Create/push the GitHub project only within the user's authorized repository destination; a prepared local tree is not a published repository.
