# Contributing

[English](CONTRIBUTING.md) · [فارسی](CONTRIBUTING.fa.md)

Thank you for improving Market Analysis Audit Lab. Contributions should make evidence easier to inspect, uncertainty harder to hide, and the software safer to operate.

## Before opening work

1. Search existing issues and pull requests.
2. Open an issue for a new provider, schema change, scoring-policy change, or large UI/architecture proposal.
3. Never attach real API keys, cookies, private transcripts, copyrighted media, private audit bundles, or personal data.
4. Use only synthetic or clearly licensed fixtures in tests and documentation.
5. Read the [methodology](docs/en/methodology.md), [security policy](SECURITY.md), and [legal guide](docs/en/legal-and-rights.md).

Security vulnerabilities must follow [SECURITY.md](SECURITY.md), not the public issue tracker.

## Development setup

```bash
cp .env.example .env
docker compose build
docker compose run --rm audit-lab python -m audit_lab.cli demo
docker compose run --rm audit-lab python -m unittest discover -s tests -v
```

Local Python development is also supported when the documented Python version and locked dependencies are installed:

```bash
python -m unittest discover -s tests -v
python -m audit_lab.cli demo --workspace ./workspace
```

## Pull-request expectations

- Keep the change focused and explain the user-visible outcome.
- Add or update tests. A bug fix should normally include a regression test.
- Preserve conservative exclusions and evidence traceability.
- Update English and Persian documentation together; every `docs/en/*.md` file must have a `docs/fa/*.md` counterpart.
- Update schemas, schema versions, prompt hashes, policy versions, changelog, and migration notes when relevant.
- Document network access, data recipients, cost, new secrets, licenses, and privacy impact.
- Do not weaken validation to make a fixture pass.
- Do not present a score as a trading win rate, profitability proof, or analyst certification.

## Adding a data provider

A provider contribution must document venue, symbol mapping, interval, timezone, adjustments, gaps, rate limits, licensing/redistribution limits, and exact-versus-proxy status. Preserve raw provenance and normalized hashes. Tests must use synthetic local fixtures; live provider calls must not be required for the default test suite.

## Changing AI behavior

Treat prompts, schemas, model settings, validation, retry policy, and deterministic exclusions as versioned methodology. Explain what data is sent, add adversarial tests for prompt injection and malformed structured output, and show how caches are invalidated. Do not make a model response the authoritative transcript excerpt.

## Documentation style

Use plain language, ISO dates, UTC timestamps, and concrete limitations. Persian documents use UTF-8, Persian `ی` and `ک`, correct half-spaces, an RTL wrapper, and LTR fenced code. Keep headings and examples semantically equivalent across languages.

## Commits and sign-off

Use small, descriptive commits. Every commit must include a Developer Certificate of Origin sign-off:

```text
Signed-off-by: Your Name <you@example.com>
```

Use `git commit -s`. By signing off, you certify the statement in [DCO](DCO).

## Review and merge

Maintainers evaluate correctness, methodology, rights/privacy, security, tests, documentation parity, and maintainability. Approval is not guaranteed. Significant methodology changes should have an issue and decision record before merge. Maintainers may close changes that expose private data, create legal risk, or undermine evidentiary fairness.
