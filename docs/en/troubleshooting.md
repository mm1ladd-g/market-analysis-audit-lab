# Troubleshooting

[English](troubleshooting.md) · [فارسی](../fa/troubleshooting.md) · [Documentation](index.md)

Start with `python -m audit_lab.cli doctor` and `status`. Never paste `.env` or full private artifacts into an issue.

| Symptom | Check |
|---|---|
| Source configuration missing | Set analyst, channel URL/ID, dates, and rights acknowledgement |
| Collection stops at rights gate | Confirm permission/terms; do not bypass the gate to scrape content |
| Date boundary not proven | Increase `MAX_SCAN_ITEMS` only after estimating upload volume |
| No eligible subtitle | Review `SUBTITLE_LANGUAGES`; use an authorized provided transcript or record exclusion |
| OpenAI stage refuses | Set API mode, key, valid model IDs, and cost acknowledgement |
| Model unavailable | Choose an available exact ID; changing it invalidates cache and methodology records |
| Rate limit/timeout | Lower concurrency, preserve successful cache, rerun only failures |
| Market asset unsupported | Add a reviewed asset map and defensible provider; do not guess a proxy |
| CSV rejected | Check UTC/timezone, OHLC column mapping, duplicates, sorting, interval, and gaps |
| Incomplete window | Wait for maturity or keep `insufficient_data`; never shorten silently |
| Hash mismatch | Stop publication; restore exact bytes or rebuild the affected stage |
| Persian text broken | Verify UTF-8, Persian font/OFL, RTL wrapper, and LTR chart/hash elements |
| Public site exposes evidence | Remove public binding, rotate secrets if needed, review static/API routes and logs |

Cache is evidence-keyed. Do not delete it reflexively; inspect why a miss occurred. `--force` can spend money and should be recorded.
