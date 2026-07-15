# Configuration reference

[English](configuration.md) · [فارسی](../fa/configuration.md) · [Documentation](index.md)

Configuration is loaded from environment variables and optional `.env`. Never commit `.env`. `python -m audit_lab.cli doctor` prints a redacted summary.

## Source and window

| Variable | Purpose |
|---|---|
| `PROJECT_NAME` | Neutral report title |
| `ANALYST_NAME` | Subject display name; required for real collection |
| `SOURCE_MODE` | `provided` for operator-supplied authorized inputs or `youtube` for the gated platform adapter |
| `PROVIDED_SOURCES_DIR` | Import directory used by `provided` mode |
| `YOUTUBE_CHANNEL_URL` / `YOUTUBE_CHANNEL_ID` | Source identity; both required and cross-checked |
| `START_DATE` / `END_DATE` | Inclusive ISO date window |
| `MAX_AUDIT_DAYS` | Guardrail against accidental oversized runs |
| `MAX_SCAN_ITEMS` | Maximum uploads scanned while proving the lower boundary |
| `SOURCE_RIGHTS_ACKNOWLEDGED` | Explicit operator attestation; required, but not legal permission |
| `SUBTITLE_LANGUAGES` | Ordered comma-separated subtitle preference |
| `REQUIRE_SUBTITLES_FOR_AUDIT` | Exclude rather than invent evidence when captions are absent |
| `STRICT_SOURCE_CHANNEL` | Reject metadata from a different channel |
| `COLLECT_THUMBNAILS` | Off by default; enable only when necessary and permitted |
| `TRANSCRIPTION_FALLBACK` | Enables authorized audio transcription for missing captions |
| `OPENAI_TRANSCRIPTION_MODEL` | Transcription model supported by the adapter |
| `TRANSCRIPTION_LANGUAGE` / `TRANSCRIPTION_PROMPT` | Optional transcription hints; never use to rewrite meaning |
| `TRANSCRIPTION_CHUNK_SECONDS` | Authorized-audio chunk size |
| `RETAIN_RAW_AUDIO` | Off by default; keep raw audio only when necessary and permitted |

## Scope and outcomes

| Variable | Purpose |
|---|---|
| `AUDIT_SCOPE_CATEGORIES` | Comma-separated lowercase category IDs |
| `CATEGORY_OVERRIDES_FILE` | Optional reviewed JSON mapping of video IDs to categories |
| `ASSET_MAP_FILE` | Optional reviewed JSON asset/provider mapping |
| `PRICE_OUTCOME_ONLY` | Keeps contextual claims outside price scoring |
| `INTERNATIONAL_MARKET_PROVIDER` | `csv` for operator-supplied exact/licensed rows or `yfinance` for documented proxies |
| `MARKET_CSV_DIR` | Directory containing configured CSV series |
| `REPORT_DEFAULT_LANGUAGE` | `en` or `fa` |
| `PUBLICATION_MODE` | `private` by default; public mode requires publication review |
| `PUBLIC_CLAIM_LEDGER` | Off by default because claim evidence may reproduce transcript text |

Overrides are methodology inputs. Include them in the final hash inventory and review them for subject-specific favoritism.

`PUBLICATION_MODE` is enforced. `private` labels the page as a local preview and closes PDF/claim downloads. In `public` mode, `review accept` must match the current collection, outcome, and scoring hashes; after regenerating and inspecting the dashboard, PDF, and any optional public ledger, `review publication-accept` must bind those exact presentation artifacts. Public `finalize` and downloads remain blocked until both checkpoints are current. `PUBLIC_CLAIM_LEDGER=true` is an additional opt-in; the default reports-only web container intentionally does not mount private analysis ledgers.

## OpenAI

| Variable | Purpose |
|---|---|
| `AUDIT_MODE` | `offline` or `api` |
| `OPENAI_API_KEY` | Runtime secret; never logged or built into an image |
| `API_COST_ACKNOWLEDGED` | Required before uncached paid work |
| `OPENAI_MODEL_CLAIM_EXTRACTION` | Exact available model ID for extraction |
| `OPENAI_MODEL_SCORING` | Exact available model ID for scoring |
| `OPENAI_*_REASONING_EFFORT` | Model reasoning setting |
| `OPENAI_CONCURRENCY` | Parallel calls; begin low |
| `OPENAI_TIMEOUT_SECONDS` / `OPENAI_MAX_RETRIES` | Failure controls |
| `OPENAI_*_USD_PER_1M` | Optional operator-maintained cost estimates |

Do not copy model names or prices from an old example without checking current official documentation and account availability.

## Storage

`WORKSPACE_DIR` defaults to `/workspace` in Docker. Use a dedicated, access-controlled volume. Do not point it at the repository root, home directory, or shared public web root.
