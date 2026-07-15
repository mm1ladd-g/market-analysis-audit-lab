# Release process

[English](release-process.md) · [فارسی](../fa/release-process.md) · [Documentation](index.md)

1. Freeze scope and update version, schemas, prompts/policies, docs, roadmap, citation, and changelog.
2. Confirm no real audit instance, person, channel, private domain, media, transcript, report, workspace, credential, cookie, cache, or local path is tracked.
3. Run English/Persian filename parity, Markdown/link, RTL, accessibility, unit, integration, synthetic demo, and clean-clone Docker tests.
4. Run full-history secret scan, static analysis, dependency review, license inventory, SBOM, container vulnerability scan, and `docker history` inspection.
5. Build from the tagged commit with pinned dependencies/base; run as non-root and verify localhost binding.
6. Verify synthetic collection/final hashes and corrupt-file failure tests.
7. Review YouTube/provider/OpenAI links and remove stale prices or “latest model” claims.
8. Have a maintainer review rights, privacy, security, methodology, and release artifacts.
9. Create an annotated `vMAJOR.MINOR.PATCH` tag on `main`. The release workflow verifies it against `pyproject.toml`, then creates source archives, Python packages, the versioned multi-architecture image, dependency/container SBOMs, a dependency-license inventory, vulnerability reports, provenance attestations, and SHA-256 checksums. Never attach `.env` or workspace output.
10. Publish release notes with breaking changes, migrations, limitations, supported versions, and security contact; verify GitHub license/security detection.

If any critical check fails, do not publish. Amend through a new candidate, never by silently replacing a released asset.

The workflow first pushes the multi-architecture candidate by digest without a public version or `latest` tag. It inventories, generates SBOMs for, scans, and inspects the exact amd64 and arm64 manifests, then applies the immutable version tag only after every gate passes. That verified digest is promoted to `latest` only after the GitHub release succeeds. GitHub OIDC attestations cover both the container digest and downloadable files. A cryptographically signed Git tag is encouraged but is distinct from the required annotated tag and provenance attestations.
