# Quick start

[English](quickstart.md) · [فارسی](../fa/quickstart.md) · [Documentation](index.md)

## 1. Run the synthetic demo

Prerequisites: Git, Docker Engine/Desktop, Docker Compose v2, and enough space for the image and `workspace/`.

```bash
git clone https://github.com/mm1ladd-g/market-analysis-audit-lab.git
cd market-analysis-audit-lab
umask 077 && cp .env.example .env
docker compose build
docker compose run --rm audit-lab python -m audit_lab.cli demo
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
docker compose run --rm audit-lab python -m audit_lab.cli finalize --synthetic-demo --workspace /workspace
docker compose run --rm audit-lab python -m audit_lab.cli verify-final --synthetic-demo --workspace /workspace
```

The demo uses deterministic fictional fixtures and makes no provider or API calls. Each run
records its own UTC creation time, so complete bundle and PDF hashes can differ between runs even
when both verify successfully. A fresh, uncached image build still needs network access. This is
the only supported first run. Inspect `workspace/SYNTHETIC_DEMO.txt`,
`workspace/final_audit_summary.json`, and `workspace/final_audit/file_hashes.csv`.

## 2. Configure an authorized source

Read [legal and rights](legal-and-rights.md). Edit `.env` with nonempty `ANALYST_NAME`, `YOUTUBE_CHANNEL_URL`, `YOUTUBE_CHANNEL_ID`, inclusive `START_DATE`/`END_DATE`, category scope, subtitle languages, and market provider. Confirm `SOURCE_RIGHTS_ACKNOWLEDGED=true` only when collection and processing are permitted.

```bash
docker compose run --rm audit-lab python -m audit_lab.cli doctor
docker compose run --rm audit-lab python -m audit_lab.cli smoke
```

## 3. Collect and freeze evidence

```bash
docker compose run --rm audit-lab python -m audit_lab.cli collect
docker compose run --rm audit-lab python -m audit_lab.cli manifest
docker compose run --rm audit-lab python -m audit_lab.cli verify
```

Inspect the inclusion/exclusion ledger before proceeding. Missing subtitles, wrong channel IDs, unknown categories, duplicates, and out-of-window items must remain visible.

## 4. Make one paid test

Set `AUDIT_MODE=api`, `OPENAI_API_KEY`, currently available model IDs, and `API_COST_ACKNOWLEDGED=true`. Pricing variables are optional estimates; verify current official prices yourself.

```bash
docker compose run --rm audit-lab python -m audit_lab.cli extract-claims --limit 1
```

Review the claim artifact, evidence lines, conditions, levels, scoreability, usage, model ID, and hashes. Then run the remaining extraction.

## 5. Outcomes, scoring, report, and verification

```bash
docker compose run --rm audit-lab python -m audit_lab.cli extract-claims
docker compose run --rm audit-lab python -m audit_lab.cli fetch-outcomes
docker compose run --rm audit-lab python -m audit_lab.cli score
docker compose run --rm audit-lab python -m audit_lab.cli report
docker compose run --rm audit-lab python -m audit_lab.cli review accept \
  --reviewer "Reviewer name" --notes "Evidence, scoring, translation, and limitations checked"
docker compose run --rm audit-lab python -m audit_lab.cli report
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
# Inspect dashboard_data.json, the PDF, and any optional public ledger before continuing.
docker compose run --rm audit-lab python -m audit_lab.cli review publication-accept \
  --reviewer "Reviewer name" --notes "Dashboard, PDF, and optional public ledger checked"
docker compose run --rm audit-lab python -m audit_lab.cli finalize
docker compose run --rm audit-lab python -m audit_lab.cli verify-final
```

The PDF is written to `workspace/reports/audit-report.pdf` with Persian first and English second. Start the local dashboard with `docker compose up`; it listens only on `127.0.0.1:${HOST_PORT:-18765}` by default.

Keep `PUBLICATION_MODE=private` while preparing and reviewing. For a real release, change it to `public`, generate the pending report, accept the evidence, regenerate and inspect the dashboard/PDF and optional ledger, record `review publication-accept`, then finalize without changing an accepted artifact. Any later report, PDF, ledger, or review change requires publication acceptance and `finalize` again. Do not publish automatically; complete the [fair-publication checklist](fairness-and-publication.md) first.
