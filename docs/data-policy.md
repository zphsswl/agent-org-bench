# Data and publication policy

## Publish by allowlist

Review and export source, offline tests, documentation, public examples, curated aggregate decisions and approved retired benchmark material. Do not copy a workspace or an entire experiment directory into a public repository.

Never include:

- provider credentials, authentication headers, `.env` files or local tokens;
- account identifiers, balances, pricing/funding records or provider-charge reports;
- raw `runs/`, API logs, private/current test cases or unreviewed prompt traces;
- native-pilot AES ciphertext, scoring keys or root-scoring artifacts;
- active holdout seeds that allow the public generator/reference implementation to reconstruct hidden cases.

Gitignore rules prevent some accidental additions; they do not remove already tracked files. Inspect the staged-file list and file contents before publishing.

## Holdouts and retired releases

Active evaluation material stays outside the public tree. Publish commitments/hashes and high-level protocol metadata without revealing reconstructible active cases. Once retired and explicitly approved, a benchmark version may have a separate reviewed release; do not silently replace the active holdout with public data.

The public reproduction seed is a different demonstration dataset. A task seed is not a model sampling seed, and new seeds from one generator are not automatically out-of-distribution tasks.

## Solver access

Public evaluation feedback and final hidden scoring are separate interfaces. Solvers must not read reference implementations, archived answers, hidden cases or research-agent context. Shared filesystem identity and encryption alone do not prove adversarial access control; document the actual isolation and auditing boundary.

## Reporting

Keep raw evidence locally for audit, but distribute only reviewed summaries. Report invalidated and incomplete studies, failures and unknown usage accurately. Native and API backends remain separate; unknown measurement is not zero and not a basis for an efficiency claim.
