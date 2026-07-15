# Market data and outcome evidence

[English](market-data.md) · [فارسی](../fa/market-data.md) · [Documentation](index.md)

Market evidence must match the instrument, venue, interval, timezone, and claim being audited. A higher-resolution feed is not more accurate when it represents a different venue, a rolling futures proxy, or data with unknown rights. The audit records those choices; it does not turn a proxy into an exact instrument.

## Evidence providers

### Binance spot benchmarks

The built-in crypto mappings use Binance spot pairs such as BTC/USDT, ETH/USDT, SOL/USDT, and ETH/BTC. The collector requests one-minute bars. Completed daily archives are preferred and their published SHA-256 checksums are verified. Current-day REST rows are provisional, have no upstream archive checksum, and remain labeled separately.

USDT spot is a declared benchmark proxy when a video says “USD.” A level can touch on one venue and miss on another, so borderline cases must retain the venue and proxy disclosure.

Continuous Binance coverage is never inferred from the bars that happened to arrive. Its policy declares a 60-second cadence, a 60-second maximum gap, and a 60-second boundary tolerance. A 24-hour window therefore requires 1,440 correctly spaced bars; a sparse series cannot masquerade as a lower-frequency complete series.

### Licensed operator CSV (preferred for international markets)

Set `INTERNATIONAL_MARKET_PROVIDER=csv` and `MARKET_CSV_DIR` to use an exact or licensed feed. Each series requires two files: an OHLC CSV and a JSON metadata sidecar. See [`configs/README.md`](../../configs/README.md) for the complete contract.

For `series_key=GC=F`, filenames are `GC_F.csv` and `GC_F.metadata.json`. The CSV requires:

```text
timestamp_utc,open,high,low,close,volume
2026-06-01T13:00:00Z,2340.1,2344.8,2338.6,2342.9,1204
```

Every timestamp must include an explicit offset. Rows must be strictly increasing and unique. OHLC values must be finite and satisfy `low <= open/close <= high`; optional volume cannot be negative. The adapter rejects invalid data instead of sorting, deduplicating, dropping, or repairing it.

The sidecar declares:

- schema and matching `series_key`;
- vendor symbol and venue;
- source IANA timezone and display interval;
- exact cadence in seconds;
- whether timestamps denote bar open or bar close;
- `continuous` or `non_continuous` session behavior;
- maximum legitimate gap, boundary tolerance, and minimum bars per 24 hours;
- license name, source URL when available, and redistribution mode.

Close-stamped bars are normalized to bar-open timestamps by subtracting the declared cadence before outcome alignment. Both the input and sidecar hashes are preserved in the normalized artifact.

For a non-continuous market, cadence alone is not enough: weekends, exchange closures, and overnight breaks create legitimate gaps. The operator must declare a defensible maximum session gap, a window-boundary tolerance, and a minimum evidence count. The declared minimum cannot be lower than 10% of the full-day count implied by cadence. A window is incomplete when it violates any declaration. These declarations are evidence assumptions, not an exchange calendar; use a verified calendar-aware adapter when session precision is material.

### yfinance convenience mode

`INTERNATIONAL_MARKET_PROVIDER=yfinance` uses an unofficial Yahoo client for prototyping. It can return hourly index, ETF, FX, or futures proxies instead of the charted instrument; history can change and availability is not guaranteed. The output labels the provider, symbol, hourly resolution, proxy note, and locally calculated hash. It must not be described as exchange-grade evidence.

The application declares a conservative non-continuous hourly coverage policy for this mode. That policy detects obvious sparse data but does not prove an exchange calendar. Prefer licensed CSV data for publication-grade decisions.

## Validation and coverage rules

Before an outcome window can be complete, the normalized series must pass all of these checks:

1. ISO-8601, timezone-aware UTC normalization.
2. Strictly increasing, unique timestamps.
3. Finite and correctly ordered OHLC values.
4. Declared cadence alignment.
5. No gap beyond the declared continuous/session maximum.
6. Enough bars for the declared market policy.
7. A final bar close enough to the half-open window boundary.
8. The full wall-clock outcome horizon has elapsed.

Outcome windows are half-open: `[entry, entry + 24h)` and `[entry, entry + 48h)`. Entry is the first eligible bar at or after publication, subject to the declared maximum gap. A bar exactly at the horizon belongs to the next window and cannot affect the current high, low, close, or level event.

If any check fails, the window is labeled with a machine-readable reason such as `coverage_policy_missing`, `invalid_market_series`, or `source_coverage_gap`; it is not sent forward as complete scoring evidence.

## Level and event evidence

Numeric price levels—including values such as `2000` that can resemble a year—remain valid when supplied as structured price levels. Numbers explicitly marked as percentages, durations, or years are excluded. Level touches use bar high/low; first close above/below uses ordered bar timestamps. Aggregate high and low alone cannot prove intrabar event order.

## Integrity, safety, and licensing

Logical `series_key` values and Binance symbols are validated before they can influence URLs or filenames. Traversal, slashes, URLs, control characters, and unsafe symbols are rejected. Generated files and raw Binance downloads must resolve beneath `WORKSPACE_DIR`, including through symlinks.

Hashes prove that a local artifact has not changed relative to its recorded digest; they do not prove that a vendor feed was correct. Upstream Binance checksums add source-integrity evidence for completed archives. Operator CSV files have local input, sidecar, and normalized-output hashes.

Market-data licenses may prohibit redistribution. Public reports should normally publish derived evidence and provenance, not raw vendor rows. A sidecar redistribution label records the operator’s assertion but does not create legal permission. Confirm venue, contract roll/corporate-action treatment, timestamp semantics, and publication rights with the provider.
