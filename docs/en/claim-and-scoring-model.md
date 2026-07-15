# Claim and scoring model

[English](claim-and-scoring-model.md) · [فارسی](../fa/claim-and-scoring-model.md) · [Documentation](index.md)

## Claim types

`directional`, `level`, `scenario`, `risk_warning`, `macro_context`, and `not_scoreable` describe structure. `scoreable`, `conditional_scoreable`, and `not_scoreable` determine evaluation eligibility. Conditions and invalidations must remain explicit; uncertainty words must not be strengthened.

Each claim records a stable ID, video/date/category, faithful concise text, canonical source excerpt and line range, assets, levels as transcript text, direction, condition, invalidation, horizon, scoreability reason, transcript hash, and extraction confidence. Evidence is capped at eight consecutive lines and 2,000 characters; every material numeric level must occur in those cited lines after Persian/Arabic digit normalization. Instruction-like transcript content is flagged for human review rather than obeyed.

## Outcome status

An asset is `available`, `unsupported_asset`, `out_of_scope_non_price`, or unavailable/incomplete with a reason. Outcome evidence records provider, venue, symbol, resolution, proxy note, raw/normalized hashes, 24/48-hour completeness, OHLC statistics, and ordered level events when resolution permits.

The machine policy supports explicit 24-hour and 48-hour horizons. A daily claim with no explicit horizon uses the documented 24-hour default; an unsupported explicit horizon is excluded before scoring. One window is selected per claim, and every material asset must have complete evidence for that same window—mixed 24/48-hour evidence cannot enter the denominator.

## Result categories

| Result | Counts? | Score | Meaning |
|---|---:|---:|---|
| `correct` | yes | 1.0 | Material expected path supported without prior invalidation |
| `partially_correct` | yes | 0.5 | Only part/order/approximate level supported |
| `incorrect` | yes | 0.0 | Evidence contradicts the expected path or invalidates it |
| `not_triggered` | no | 0.0 | Explicit testable condition did not activate |
| `not_scoreable` | no | 0.0 | No defensible price scoring contract or out-of-scope context |
| `insufficient_data` | no | 0.0 | Asset/window/order evidence is inadequate |

The aggregate is `100 × sum(counted scores) / counted claims`. Always show the numerator components, counted denominator, excluded denominator, and result distribution. Never label it profit, accuracy of all commentary, or trading win rate.

Validation requires each claim exactly once, fixed score/result consistency, complete supported outcome data for counted claims, and a verified trigger for counted conditional claims. AI-generated review fields are not publication approval: public finalization separately requires a named human acceptance bound to the current artifact hashes.
