# Security policy

[English](SECURITY.md) · [فارسی](SECURITY.fa.md)

## Supported versions

Until version 1.0, security fixes are applied to the latest tagged release and the default branch. Older pre-1.0 releases may receive no backports. Release notes identify any exceptional support window.

## Report a vulnerability privately

Use GitHub's **Report a vulnerability** form under the repository Security tab. Do not open a public issue, discussion, pull request, or paste exploit details into logs. If private reporting is unavailable, open a public issue containing only the sentence “Private security contact needed”; a maintainer will establish a private channel.

Include, when safe:

- affected version, commit, image digest, and platform;
- minimal reproduction without real API keys or third-party personal data;
- expected and observed behavior;
- impact and whether exploitation requires network access or untrusted input;
- suggested mitigation, if known.

Maintainers will acknowledge reports on a best-effort basis, validate impact, coordinate a fix and disclosure, and credit reporters who request credit. The project does not promise a response SLA.

## Secrets

- Keep `.env`, API keys, OAuth tokens, cookies, tunnel credentials, and provider credentials outside Git.
- Never pass a key as a Docker build argument, image `ENV`, command-line flag, issue attachment, or audit artifact.
- Prefer secret managers or runtime-only environment injection for shared deployments.
- If a key is exposed, revoke or rotate it immediately; deleting a file from the latest commit is not sufficient. Scan the full Git history, release assets, container layers, caches, and logs.
- The CLI reports only whether a key exists. It must never print the secret or a reversible representation.

## Threat model

All external inputs are untrusted, including channel metadata, titles, descriptions, subtitles, transcripts, CSV files, archive members, model outputs, URLs, and rendered HTML.

Important risks include:

- prompt injection embedded in transcripts or metadata;
- path traversal, symlinks, zip bombs, decompression bombs, and oversized files;
- spreadsheet formula injection in exported CSV;
- XSS from titles, excerpts, descriptions, or model-produced text;
- SSRF and unintended redirects from configurable endpoints;
- denial of service through large channels, excessive date ranges, API retries, or concurrency;
- malicious dependency or container-image updates;
- publication of copyrighted material, personal data, or confidential API artifacts;
- exposure of unauthenticated claim/report APIs on a public interface.

The model receives evidence as data, never as trusted instructions. Structured output validation, canonical source copying, strict schemas, size limits, HTML escaping, safe archive extraction, and human review are defense-in-depth controls; none is sufficient by itself.

## Deployment baseline

- Bind to `127.0.0.1` by default.
- Before public deployment, add TLS, authentication, authorization, request limits, secure headers, log redaction, backups, and an explicit publication review.
- Run containers as a non-root user with a read-only root filesystem where possible; mount only the required workspace.
- Do not expose Docker, the host filesystem, `.env`, caches, raw evidence, or build metadata.
- Restrict egress to documented providers and review redirects.
- Pin and scan dependencies, actions, and container bases; produce an SBOM for releases.
- Treat `/api/claims`, transcript excerpts, and reports as sensitive until approved for publication.

## Security verification before release

Run tests, a full-history secret scan, dependency and license review, static analysis, container vulnerability scan, SBOM generation, and `docker history` inspection. Verify a clean clone can build and run the synthetic demo without any credential or private instance artifact.

Security controls reduce risk; they do not certify the software for financial, safety-critical, or regulated use.
