# Security

[English](security.md) · [فارسی](../fa/security.md) · [Documentation](index.md)

Read the authoritative [security policy](../../SECURITY.md) and report vulnerabilities privately.

Treat transcripts, metadata, CSV, URLs, archives, provider responses, model output, and HTML as malicious until validated. Protect against prompt injection, XSS, SSRF, archive traversal, formula injection, oversized files, resource exhaustion, secrets in logs, and unauthenticated evidence APIs.

Run locally by default. A public deployment requires TLS, authentication and authorization, rate and size limits, secure headers, escaped output, restricted mounts/egress, a non-root container, backup/restore testing, redacted logging, dependency pinning, SBOM, vulnerability scan, and an explicit evidence-publication review.

Public access also fails closed at the artifact boundary. After the evidence review, `review publication-accept` must bind the inspected dashboard, PDF, and explicitly enabled claim ledger. `finalize` requires that current checkpoint and must verify the completed final directory and ZIP before atomically activating a hash-bound publication manifest. The dashboard and downloads must match the activated hashes on every request. Replacing an artifact, rerunning `report`, regenerating the PDF, or changing either review ledger closes access until publication acceptance is repeated and `finalize` succeeds again.

Never place credentials in Git, Docker layers, command history, reports, screenshots, or support issues. Rotate an exposed key and scan full history and release assets.
