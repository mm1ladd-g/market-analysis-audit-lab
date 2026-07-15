# Privacy policy and operator guide

[English](PRIVACY.md) · [فارسی](PRIVACY.fa.md)

This repository is local-first and contains no telemetry code by design. A deployed operator controls the workspace, network access, retention, and publication. That operator is responsible for an accurate privacy notice and applicable law.

## Data processed locally

Depending on configuration, the workspace may contain channel metadata, public identifiers, titles, descriptions, subtitle files, normalized transcripts, thumbnails, timestamps, market rows, extracted claims, AI responses, token usage, logs, hashes, dashboards, and final archives. Some of this may identify a person or reproduce protected expression.

The public source repository contains only synthetic demo data. Real audit instances are never bundled.

## Data sent to OpenAI

When `AUDIT_MODE=api`, claim extraction sends configured video metadata and the relevant line-numbered transcript. Scoring sends extracted claims and structured market-outcome evidence. Requests include configured model and reasoning settings and set `store=false`, but operators must consult current OpenAI documentation and their account terms for actual processing, retention, regional, and control behavior. Offline and synthetic-demo paths do not require an OpenAI request.

The application records response IDs, returned model IDs, token usage, hashes, and accepted structured output for reproducibility. It must not record the API key.

## Other network recipients

Collection and outcome stages may contact the configured source platform, Binance, Yahoo through `yfinance`, or endpoints selected by a custom provider. Embedded players or remote fonts can create additional browser requests; public deployments should document or remove them. Review every provider's terms and privacy practices.

## Data minimization

- Keep thumbnails and raw media disabled unless necessary and permitted.
- Select the smallest justified date range and source set.
- Publish short, necessary evidence excerpts rather than full transcripts.
- Do not collect comments, viewer identities, faces, emails, or account data unless the methodology genuinely requires it and a lawful basis exists.
- Redact secrets, local paths, cookies, response payloads not needed for review, and personal data unrelated to the claim.
- Separate private evidence storage from public dashboard assets.

## Retention and deletion

Define retention before collection. Suggested categories are raw source, normalized evidence, AI cache, logs, market data, reports, and final bundles, each with an owner and expiry. A hash inventory is not a reason to retain content indefinitely.

To delete a local instance, stop the service and securely remove its mounted workspace, backups, exported reports, logs, release assets, and any external object-storage copies. Removing the Docker container alone does not delete a bind-mounted workspace. Deleting a local copy does not delete data already sent to a provider; use that provider's controls where available.

## Public deployment

Before exposing an audit:

1. run a rights, privacy, and human-review checklist;
2. remove raw transcripts, unnecessary excerpts, local paths, credentials, caches, and private logs;
3. authenticate sensitive APIs and disable directory listing;
4. publish an operator-specific privacy notice naming every recipient and retention period;
5. provide correction, objection, and deletion contact paths where applicable;
6. disclose sponsored or commissioned relationships.

This file is a project baseline, not legal advice and not a substitute for an operator-specific privacy policy.
