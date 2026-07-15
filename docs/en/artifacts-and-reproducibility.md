# Artifacts and reproducibility

[English](artifacts-and-reproducibility.md) · [فارسی](../fa/artifacts-and-reproducibility.md) · [Documentation](index.md)

## Workspace

```text
raw/                         authorized source files
logs/collection_run.json     scan completeness and boundary proof
audit_pack/manifest.json     inclusion and exclusion ledger
audit_pack/file_hashes.csv   source-pack SHA-256 inventory
audit_pack/transcripts/      canonical normalized evidence
analysis/claims/             per-video and aggregate claim artifacts
analysis/outcomes/           market rows, provenance, and claim windows
analysis/scores/             decisions and aggregate denominator
review/human_review.json     hash-chained evidence-review checkpoint
review/publication_review.json  exact public-artifact acceptance checkpoint
cache/                       evidence-keyed API artifacts
reports/dashboard_data.json  presentation input
reports/publication_manifest.json  activated public artifact hashes
final_audit/                 complete verified bundle
```

The collection ID is derived from the source snapshot, not a promotional title. Finalization rejects mismatched collection IDs, incomplete stages, stale schema/policy versions, per-video/aggregate ledger disagreement, broken transcript or market-source hashes, inconsistent outcome hashes, scoring fingerprints, and recomputed denominator/result aggregates.

## Two meanings of reproducibility

**Artifact verification** recomputes size and SHA-256 values, tests ZIP integrity, and proves the inspected bytes match the recorded bundle.

**Computational rerun reproducibility** asks whether new collection, provider, or API calls produce equivalent results. It is limited by mutable platform metadata, revised market history, retired models, probabilistic responses, dependency changes, and time. Hash verification does not establish truth, completeness, legality, or identical rerun behavior.

## Reproduction record

Preserve the Git commit/tag, container digest, sanitized config, UTC retrieval times, source boundaries, exclusion ledger, provider/venue/symbol/interval, raw and normalized hashes, model requested/returned IDs, reasoning settings, response IDs, token usage, prompt/schema/policy hashes, cache keys, tests, reviewer, and final ZIP hash.

Never include secrets, cookies, local usernames, or unneeded private source content. A verifier should be able to run `verify` and `verify-final` without an API key or network call.

The final bundle contains `components/runtime_settings.public.json` (sanitized settings plus application version), both hash-chained review ledgers for a public audit, the activated publication manifest, reviewed policy configs and hashes, the normalized in-range provided-source manifest when applicable, and a portable `components/market_evidence/` copy with a relative-path/hash manifest. It does not copy `.env`, the API key, transcription prompt text, or absolute operator paths.
