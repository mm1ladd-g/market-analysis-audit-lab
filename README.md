# Market Analysis Audit Lab

[English](README.md) · [فارسی](README.fa.md) · [Documentation](docs/en/index.md) · [مستندات](docs/fa/index.md)

[![CI](https://github.com/mm1ladd-g/market-analysis-audit-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/mm1ladd-g/market-analysis-audit-lab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mm1ladd-g/market-analysis-audit-lab)](https://github.com/mm1ladd-g/market-analysis-audit-lab/releases)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Market Analysis Audit Lab is a local-first, Dockerized research system that turns authorized, time-stamped market-analysis transcripts and market data into a reviewable evidence bundle. AI helps structure claims and apply explicit rules; AI output is never treated as source evidence.

The system evaluates configured claims. It does **not** provide investment advice, prove profitability, certify an analyst, or predict future performance.

> [!CAUTION]
> Only process material you own, are authorized to use, or may lawfully use. A public URL is not a content license. Set `SOURCE_RIGHTS_ACKNOWLEDGED=true` only after checking the applicable platform terms, licenses, permissions, and law.

## Why this project exists

Market commentary often contains several conditional paths rather than one prediction. A fair audit must preserve those conditions, triggers, invalidations, time horizons, and exclusions. This project creates an inspectable chain:

```text
authorized source collection
  → date/channel validation
  → canonical transcript evidence + SHA-256 inventory
  → structured claim extraction
  → time-aligned market outcomes
  → deterministic exclusions + conservative scoring
  → dashboard data + hash-verifiable final bundle
```

Every result can trace back to a source line range, a transcript hash, a market-data artifact, an evaluation window, a prompt and schema version, and a scoring decision. A percentage is scenario-outcome alignment among counted, activated, verifiable claims—not a trading win rate.

## Safe five-minute start

The bundled demo is fully synthetic: running it makes no provider or API calls and requires no API key. A fresh, uncached Docker build still needs network access to fetch the base image and pinned dependencies. Every identity, transcript, price, claim, and result in the demo is fictional.

```bash
umask 077 && cp .env.example .env
docker compose build
docker compose run --rm audit-lab python -m audit_lab.cli demo
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
docker compose run --rm audit-lab python -m audit_lab.cli finalize --synthetic-demo --workspace /workspace
docker compose run --rm audit-lab python -m audit_lab.cli verify-final --synthetic-demo --workspace /workspace
```

If the Makefile is available, the equivalent workflow is:

```bash
make setup
make build
make demo
```

`make demo` also creates the Persian-first bilingual PDF, rebuilds the final integrity bundle, and verifies it.

The demo writes to the mounted `workspace/` directory. Inspect `workspace/final_audit_summary.json` and the generated hash inventories before configuring a real source.

## Real audit workflow

1. Read [legal and source-rights requirements](docs/en/legal-and-rights.md), [privacy](docs/en/privacy.md), and [methodology](docs/en/methodology.md).
2. Copy `.env.example` to `.env`; add a subject, channel, inclusive date range, subtitle preferences, scope, and data providers.
3. Confirm source rights and, separately, paid API use. These acknowledgements are deliberate safety gates, not substitutes for permission or legal review.
4. Run one video through claim extraction and inspect it before spending on a full run.
5. Verify both the collection pack and final bundle. Human-review every public conclusion.

```bash
make doctor
make smoke
make collect
make manifest
make verify
make extract-claims ARGS="--limit 1"
make fetch-outcomes
make score ARGS="--limit 1"
make report
make pdf
make finalize
make verify-final
```

For a complete stage-by-stage explanation, see the [operator runbook](docs/en/workflow.md). Do not run `collect` against third-party content merely because it is publicly viewable.

## Inputs and providers

- **Source evidence:** the collector can use configured subtitle tracks and records source metadata, but operators remain responsible for access and content rights. The public project never bundles a real audit instance.
- **AI:** claim extraction and interpretive scoring use the OpenAI Responses API only when `AUDIT_MODE=api`. Transcripts and structured market evidence are sent to the configured service; see [OpenAI data flow and cost](docs/en/openai-models-and-cost.md).
- **Crypto outcomes:** supported crypto pairs use Binance public spot archives or API rows with provenance and checksum information where available.
- **International outcomes:** `csv` is the preferred path for licensed/exact data. `yfinance` is a convenient, unofficial Yahoo wrapper and may provide hourly proxy instruments; it is not an exchange-grade or guaranteed feed.

## Trust boundaries

- The model selects evidence line ranges; application code copies the canonical excerpt from the hashed transcript.
- Unsupported assets, incomplete windows, non-triggered conditions, vague claims, and out-of-scope context do not become wins.
- Cached AI artifacts are keyed to evidence, prompt, policy, model, and schema fingerprints.
- Hash verification proves that an existing artifact did not change. It does not guarantee that a later API rerun will return identical language or judgments.
- Source transcripts can contain prompt-injection text. They are untrusted evidence, not instructions. Public results require human review.

## Repository map

```text
audit_lab/       pipeline, schemas, prompts, models, CLI, and web application
tests/           deterministic unit and integration tests
docs/en/         complete English documentation
docs/fa/         complete Persian documentation
workspace/       generated local evidence; ignored by Git and Docker build context
```

Generated real-world evidence, portraits, thumbnails, transcripts, API caches, credentials, audit reports, and deployment configuration do not belong in this repository.

## Documentation

- [Quick start](docs/en/quickstart.md)
- [Configuration reference](docs/en/configuration.md)
- [Architecture](docs/en/architecture.md)
- [Methodology and scoring](docs/en/methodology.md)
- [Transcripts and language](docs/en/transcripts-and-language.md)
- [Market data](docs/en/market-data.md)
- [Reproducibility](docs/en/artifacts-and-reproducibility.md)
- [Security](SECURITY.md) and [privacy](PRIVACY.md)
- [Legal rights](docs/en/legal-and-rights.md) and [fair publication](docs/en/fairness-and-publication.md)
- [Troubleshooting](docs/en/troubleshooting.md)

## Project status

This is pre-1.0 research software. Interfaces and artifact schemas may change with documented migrations. It is designed to make limitations and uncertainty visible, not to automate reputation judgments.

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md), and [Governance](GOVERNANCE.md). Report security vulnerabilities through the private process in [SECURITY.md](SECURITY.md), never a public issue.

## License

Original project code and documentation are licensed under the Apache License 2.0. Third-party dependencies and assets retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [ASSET_LICENSES.yml](ASSET_LICENSES.yml). The project license does not grant rights to source videos, transcripts, portraits, trademarks, or market datasets supplied by an operator.
