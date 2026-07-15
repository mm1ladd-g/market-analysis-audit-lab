# Operator configuration

Copy the example files into `configs/local/` and edit the copies. The local directory is ignored by Git.

- `categories.example.json` adds keyword rules and exact video-ID overrides.
- `assets.example.json` maps transcript symbols to market series and optional Binance archive symbols.
- CSV series use the validated `series_key` as their filename; `^` and `=` become `_` in filenames.

## Safe identifiers

`series_key` is a logical identifier, not a path or URL. It must be 1–64 ASCII characters and may contain only letters, digits, `^`, `=`, `.`, `_`, or `-`. Binance symbols must be 5–20 uppercase letters or digits (for example, `BTCUSDT`). Traversal strings, slashes, URLs, lowercase Binance symbols, control characters, and symlink escapes are rejected. All generated market artifacts are written beneath `WORKSPACE_DIR`.

## Licensed CSV contract

For a resolved key such as `GC=F`, place both files below in `MARKET_CSV_DIR`:

- `GC_F.csv`
- `GC_F.metadata.json`

The CSV header must contain `timestamp_utc,open,high,low,close`; `volume` is optional. Every timestamp must be ISO 8601 with an explicit offset, such as `2026-06-01T09:00:00-04:00` or `2026-06-01T13:00:00Z`. Rows must be strictly increasing and unique. Every OHLC value must be finite, `low <= open/close <= high`, and volume cannot be negative.

The matching sidecar is mandatory. Example:

```json
{
  "schema_version": "1.0",
  "series_key": "GC=F",
  "symbol": "GCQ26",
  "venue": "COMEX",
  "timezone": "America/New_York",
  "interval": "1h",
  "cadence_seconds": 3600,
  "timestamp_semantics": "bar_open",
  "session": {
    "type": "non_continuous",
    "maximum_gap_seconds": 259200,
    "boundary_tolerance_seconds": 259200,
    "minimum_bars_per_24h": 18
  },
  "license": {
    "name": "Your vendor agreement or dataset license",
    "redistribution": "derived_only",
    "source_url": "https://data-vendor.example/terms"
  }
}
```

`timezone` must be an IANA name. `timestamp_semantics` is `bar_open` or `bar_close`; close-stamped bars are deterministically shifted to their bar-open time using `cadence_seconds`. `session.type` is `continuous` or `non_continuous`. A non-continuous feed must declare its maximum legitimate closure/session gap, boundary tolerance, and a defensible minimum bar count per 24-hour outcome window; the minimum cannot be lower than 10% of the full-day count implied by cadence. A continuous feed cannot loosen its maximum gap or boundary tolerance beyond the declared cadence, its declared minimum must equal the full-day count, and each window's required bar count is calculated from cadence rather than inferred from observed rows.

`license.redistribution` is one of `none`, `derived_only`, or `raw_allowed`. This label documents operator intent; it does not grant rights. Confirm symbol construction, venue, timezone, corporate-action/roll adjustments, timestamp semantics, and redistribution rights with the data vendor before publication.
