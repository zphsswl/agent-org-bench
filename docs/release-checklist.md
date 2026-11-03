# Release checks

1. Publish only reviewed allowlisted files; preserve measured sources, registrations and outcome bytes.
2. Keep the main study separate from archived exploratory studies. Use the reader-facing layout in [the repository README](../README.md); preserve original internal identifiers in audit records.
3. Verify the manifest, local Markdown links, analysis defaults and figure paths after a layout change.
4. Run offline unit tests and the public-metric replay. CI must not receive provider credentials or run model experiments.
5. Keep raw runs, private cases, provider logs, credentials and account data outside publication.
6. Document executed sample sizes, baseline roles, failures, uncertainty and limitations. Do not turn development rankings or post-hoc slices into confirmation claims.
7. Update the publication manifest and compare the remote tree with reviewed local bytes.
8. A new replication needs its own plan, protocol, model/settings, task seeds and output directories. Never overwrite a completed registration or its outcomes.

For public reproduction see [the guide](reproducibility.md); immutable originals are in [the registration archive](../archive/registrations/README.md).
