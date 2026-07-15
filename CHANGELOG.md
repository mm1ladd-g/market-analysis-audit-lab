# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/) after the first tagged public release and uses the structure of [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.1.4] - 2026-07-16

### Fixed

- ZIP release archives now force UTC for Git archive generation, making their
  embedded timestamps and SHA-256 hashes identical across host timezones.

## [0.1.3] - 2026-07-16

### Fixed

- Release validation now verifies the separately fetched remote annotated-tag
  object, avoiding GitHub Checkout's local tag dereference while still binding
  every artifact to the exact reviewed source commit on `main`.

## [0.1.2] - 2026-07-15

### Added

- A reusable deterministic release-asset builder for the website-compatible source ZIP, source TAR.GZ, and bilingual technical-manual ZIP.
- Automated consistency checks across the Python package version, `pyproject.toml`, `CITATION.cff`, changelog, and release URL.
- Required public-audit relationship disclosure and correction-channel settings, with strict public-host and unsafe-content validation.
- A visible accountability block in the public dashboard and Persian-first/English-second PDF.

### Changed

- GitHub releases now publish website-compatible, versioned source and documentation filenames rather than differently named source archives.
- The release checksum manifest is versioned, uses portable asset basenames, and is included with every release artifact in GitHub provenance attestations.
- Evidence review, publication review, public snapshots, and final verification now hash-bind the exact accountability record; changing it invalidates both approvals and closes public endpoints.
- The read-only Compose viewer now receives the three validated public-accountability values required to verify an accepted public snapshot, while continuing to receive no API credential or `.env` mount.
- Persian technical documentation now matches the English operational coverage section-for-section, with consistent commands, configuration identifiers, legal boundaries, and terminology.
- Runtime, dashboard assets, health metadata, and market-data User-Agent now derive their version from the package version instead of stale literals.
- The bilingual PDF uses restrained cover artwork and avoids redundant synthetic-only spill pages while retaining Persian-first ordering and visible safety boundaries.

### Security

- Public correction URLs reject credentials, markup, non-HTTPS schemes, localhost, internal names, and non-global IP addresses; public DTOs reject unknown accountability fields.

## [0.1.1] - 2026-07-15

### Added

- A versioned, four-state hero-verdict policy for `supports_following`, `mixed`, `caution`, and `insufficient` outcomes.
- Result-first English/Persian dashboard copy that states the direct analytical-usefulness conclusion and its supporting denominator above the fold.

### Changed

- Positive verdicts now require at least 10 audited videos, 30 activated and judged scenarios, 50% evidence coverage, 45/100 weighted alignment, 60% full-or-partial alignment, 50% explicit conditions, and 50% named price levels.
- Every hero verdict keeps subscriber-profit limitations adjacent to the recommendation; negative results describe unsupported reliance rather than predicting viewer losses.
- The public dashboard DTO recomputes the verdict from allowlisted audit fields instead of accepting operator-supplied verdict prose.

## [0.1.0] - 2026-07-15

First public-source release.

### Added

- Neutral, configurable audit engine for arbitrary authorized analyst/channel/date inputs.
- Synthetic offline demo with no real person, channel, market event, or API call.
- Source-rights and paid-API acknowledgement gates.
- English and Persian documentation, governance, security, privacy, support, and contribution policies.
- Configurable category overrides, asset maps, CSV market input, and local-first defaults.
- Separate hash-chained evidence and exact-publication review checkpoints with stale-artifact detection.
- Separate read-only public web and rights-gated worker profiles with a redacted dashboard DTO.
- Accessible Persian/English dashboard and deterministic Persian-first/English-second PDF report.
- Hash-locked runtime, development, and release dependency environments.
- Automated source archives, Python packages, CycloneDX/SPDX SBOMs, dependency-license inventory, checksums, container digest, and provenance attestations.

### Changed

- Separated reusable engine code from all private or subject-specific audit assets.
- Framed scores as conditional scenario-outcome alignment, never trading win rate or profitability.
- Documented artifact verification separately from nondeterministic API reruns.
- Made synthetic-demo finalization explicitly independent from operator `.env` values.

### Security

- Secrets are represented with `SecretStr` and excluded from safe configuration output.
- Real instance data, credentials, workspace artifacts, and generated reports are excluded from the public repository and build context.
- The runtime container runs as non-root without package installers; worker and web services drop capabilities and use read-only filesystems, while the viewer binds only to localhost, mounts reports read-only, and receives no API key.
- CI performs full-history secret scanning, static checks, dependency review, CodeQL, critical/unfixed and fixed/high container vulnerability gates, SBOM generation, and container-history inspection.

The annotated `v0.1.0` tag identifies the exact release commit after the checks in
`docs/en/release-process.md` pass.

[Unreleased]: https://github.com/mm1ladd-g/market-analysis-audit-lab/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/mm1ladd-g/market-analysis-audit-lab/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/mm1ladd-g/market-analysis-audit-lab/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/mm1ladd-g/market-analysis-audit-lab/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/mm1ladd-g/market-analysis-audit-lab/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/mm1ladd-g/market-analysis-audit-lab/releases/tag/v0.1.0
