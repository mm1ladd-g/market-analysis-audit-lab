# Privacy

[English](privacy.md) · [فارسی](../fa/privacy.md) · [Documentation](index.md)

The authoritative project baseline is [PRIVACY.md](../../PRIVACY.md). For each audit, publish an operator-specific notice naming the controller/operator, purpose, categories of source and personal data, network recipients, retention periods, public outputs, correction/deletion contact, and applicable legal basis.

The local workspace can contain identifiers, transcripts, model responses, market data, logs, and reports. API mode sends transcripts or claim/outcome evidence to OpenAI. Collection and provider stages contact their configured services. Minimize collection, disable thumbnails by default, avoid full transcript publication, separate private and public assets, and remove local paths and secrets.

Hash inventories do not justify permanent retention. Deleting a container does not delete a bind mount, backups, exports, or data already processed by an external provider. Document deletion for every storage location.

The default `audit-web` service receives only `workspace/reports` read-only and receives no API key, raw transcript, model cache, analysis ledger, logs, home directory, or Docker socket. `/api/dashboard` is built from an explicit allowlist: it excludes claim text, transcript excerpts, scoring reasoning, video URLs, local paths, provider errors, and private review notes. URL values that are intentionally exposed have user information, query strings, and fragments removed. `/api/claims` and `/report` remain closed unless public mode is active and the current hash-bound human review is accepted; the claim endpoint additionally requires the explicit ledger flag and an intentionally available ledger.

Evidence acceptance alone does not expose those files. After inspecting the regenerated dashboard, PDF, and optional public ledger, `review publication-accept` binds their exact bytes. Public `finalize` requires that current checkpoint, first verifies the completed final bundle, and only then activates its hash-bound publication manifest. The dashboard and download endpoints fail closed if any served file is missing or replaced. Regenerating `report` or the PDF, replacing the ledger, or changing either review ledger requires publication acceptance and `finalize` again; this prevents stale approval from exposing newly written content.
