# Methodology and limitations

[English](methodology.md) · [فارسی](../fa/methodology.md) · [Documentation](index.md)

## Research question

Given a declared set of authorized videos and a declared market-data policy, what testable price scenarios were stated, which conditions activated, and how did subsequent recorded price action align? This is narrower than judging an analyst's competence, subscriber profitability, educational value, ethics, or future performance.

## Inclusion

The channel and inclusive date window are fixed before analysis. The collector must cross the lower boundary or exhaust the source. Every in-range discovery appears as included or excluded with a reason. Manual overrides are versioned methodology, never silent deletion.

## Evidence

Normalized transcripts and their line-to-cue timing sidecars are hashed. The model selects one-based consecutive line ranges; application code copies and bounds the canonical text, binds stated numeric levels to those lines, and flags instruction-like evidence for review. Claim structure preserves assets, levels, direction, condition, invalidation, horizon, scoreability, and extraction confidence. Confidence measures support for the structure, not truth.

## Outcomes

Each asset maps to a declared venue/symbol/interval. Crypto can use minute Binance spot data; international instruments may use exact operator CSV or explicitly labeled hourly proxies. Windows begin at the first usable bar after publication. The supported decision windows are 24 and 48 hours; a horizon-free daily claim uses 24 hours, while an unsupported explicit horizon is excluded. Every material asset must have the same selected complete window. Gaps, partial windows, proxy notes, timestamps, level events, and hashes remain inspectable.

## Exclusions before judgment

Vague education, unsupported assets, contextual inputs outside the price-only scope, missing data, incomplete windows, and non-triggered conditional scenarios do not enter the counted denominator. A scenario is not correct merely because its alternative never triggered.

## Interpretation

Counted results are `correct=1`, `partially_correct=0.5`, and `incorrect=0`. Other results score zero and are excluded. Multi-leg paths require ordering evidence. A target reached after explicit invalidation is not correct. Borderline proxy-dependent outcomes should be partial or insufficient, not upgraded.

## Limitations

Caption errors, ambiguous language, publication-time uncertainty, venue differences, proxy instruments, market gaps, AI variability, prompt injection, changing provider history, and human review error can affect results. Context such as ETF flows, liquidation maps, news, or macro explanations is not independently verified by a price-outcome audit. A hash verifies immutability, not factual completeness.

Report denominators, exclusions, limitations, model/provider versions, and conflicts of interest alongside every headline.
