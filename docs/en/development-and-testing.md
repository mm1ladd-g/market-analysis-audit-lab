# Development and testing

[English](development-and-testing.md) · [فارسی](../fa/development-and-testing.md) · [Documentation](index.md)

## Test locally

```bash
python -m unittest discover -s tests -v
python -m audit_lab.cli demo --workspace ./workspace
python -m audit_lab.cli verify-final --synthetic-demo --workspace ./workspace
```

The default suite is offline and synthetic. Network and paid-model tests must be separately marked, opt-in, budget-limited, and never required for a normal pull request.

Test configuration validation, date boundaries, channel mismatch, subtitle provenance, duplicate/exclusion ledgers, canonical line evidence, malformed model output, prompt injection, cache invalidation, provider gaps/timezones/proxies, ordered events, deterministic exclusions, denominator arithmetic, hashes/ZIP corruption, redaction, RTL/i18n parity, XSS, and malicious files.

New providers return normalized provenance-rich data and use fixture responses. New categories come from configuration, not named-subject hardcoding. Methodology, prompt, schema, or policy changes require version bumps, regression fixtures, migration notes, and both language docs.

Before review, run formatting/lint/type checks configured by the repository, unit tests, the synthetic end-to-end demo, documentation link/parity checks, secret scan, and container build. Do not update golden results without explaining the semantic reason.
