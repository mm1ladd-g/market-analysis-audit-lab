# Support

[English](SUPPORT.md) · [فارسی](SUPPORT.fa.md)

Community support is best-effort. The project does not provide financial, legal, compliance, data-licensing, investment, or emergency advice and does not promise response times.

## Where to ask

- **Usage or configuration:** GitHub Discussions, if enabled; otherwise a question issue.
- **Reproducible bug:** bug-report issue with synthetic or redacted inputs.
- **Feature proposal:** feature-request issue describing the evidence and safety impact.
- **Documentation:** documentation issue, naming both language pages.
- **Security vulnerability:** private process in [SECURITY.md](SECURITY.md), never a public issue.
- **Correction to a published audit:** contact that audit's operator using the correction path shown on the report. The open-source maintainers do not control independent deployments.

## Useful diagnostic information

Provide the release/commit, operating system, Docker and Compose versions, command, sanitized configuration, stage status, and minimal error. Remove keys, cookies, local usernames, channel-owner private data, full transcripts, and proprietary market rows. Prefer the synthetic demo when reproducing a bug.

Run:

```bash
python -m audit_lab.cli doctor
python -m audit_lab.cli status
python -m unittest discover -s tests -v
```

## Unsupported requests

Maintainers cannot determine whether you have legal rights to content, select trades, guarantee an audit conclusion, estimate a person's profitability, recover exposed credentials, or provide a licensed market feed. Requests to harass, defame, deanonymize, manipulate engagement, or bypass platform controls will be closed.
