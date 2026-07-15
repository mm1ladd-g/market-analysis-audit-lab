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

## Reviewed scanner exception

The repository keeps vulnerability-scan exceptions narrow, version-bound, and
reviewable in `.grype.yaml`. As of 2026-07-16, the only exception is
`CVE-2026-15308` for the CPython 3.14.6 binary. The advisory concerns a CPU
denial of service in `html.parser.HTMLParser`; this application does not import
that parser or provide a route that parses client-controlled HTML. Grype lists
the fix only in Python 3.15.0, which is not yet a stable release. The exception
must be removed when a stable patched CPython image is available and must be
reviewed no later than 2026-10-31. It does not suppress findings for any other
package, Python version, vulnerability, or severity.

## Security verification before release

Run tests, a full-history secret scan, dependency and license review, static analysis, container vulnerability scan, SBOM generation, and `docker history` inspection. Verify a clean clone can build and run the synthetic demo without any credential or private instance artifact.

Container release gates fail on every high or critical vulnerability for which
the scanner identifies an available fix. Findings without a known fix are still
reported and retained with the SBOM for review, but they do not automatically
block a release: upstream and distribution scanners can disagree about package
applicability, and an unavailable fix cannot be applied reproducibly. A scoped
exception requires a documented reachability assessment as described above.

Security controls reduce risk; they do not certify the software for financial, safety-critical, or regulated use.
