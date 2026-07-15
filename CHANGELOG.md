# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/) after the first tagged public release and uses the structure of [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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

[Unreleased]: https://github.com/mm1ladd-g/market-analysis-audit-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mm1ladd-g/market-analysis-audit-lab/releases/tag/v0.1.0
