# Architecture

[English](architecture.md) · [فارسی](../fa/architecture.md) · [Documentation](index.md)

The project is a staged file pipeline. Files, hashes, schemas, and explicit configuration form the contract; the dashboard is a consumer, not the source of truth.

```text
Source adapter → raw evidence → manifest/normalized transcripts
                                      ↓
OpenAI extraction → claim artifacts/cache
                                      ↓
Market adapters → normalized series → claim outcome windows
                                      ↓
Deterministic exclusions → OpenAI scoring → aggregate scores
                                      ↓
Dashboard/report data → final bundle → hash verification
```

## Components

- `settings.py`: validated runtime configuration and safety gates.
- `collect.py`: source scan and completeness log.
- `manifest.py`: inclusion ledger, canonical text, hashes, collection ID.
- `extract_claims.py`: Responses API Structured Outputs, evidence-line validation, cost/cache records.
- `fetch_outcomes.py`: asset resolution, Binance/CSV/yfinance adapters, normalized windows and ordered level evidence.
- `score_claims.py`: deterministic exclusions, structured scoring, fixed score mapping, aggregate denominator.
- `report.py`: presentation-only derived data.
- `finalize.py` and `verify.py`: portable evidence packs and integrity checks.
- `demo.py`: synthetic offline fixture and expected end-to-end behavior.

## Trust boundaries

Source/provider/network/model inputs are untrusted. The workspace may contain sensitive or licensed content. The public web layer must not expose it by default. OpenAI is an external data recipient in API mode. Docker isolates dependencies but is not a confidentiality boundary if mounts, ports, or the daemon are misconfigured.

## Extension points

Categories and asset maps are configurable. New transcript or market providers should implement narrow adapters that return normalized, provenance-rich artifacts. Provider-specific logic must not leak into scoring semantics. Schema or policy changes require version bumps, cache invalidation, tests, and bilingual documentation.
