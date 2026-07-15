# Outputs and dashboard

[English](outputs-and-dashboard.md) · [فارسی](../fa/outputs-and-dashboard.md) · [Documentation](index.md)

`report` creates deterministic presentation data from finalized analysis artifacts; it must not change claim or score decisions. The web dashboard and PDF are views of that data, not independent evidence stores.

## Required presentation context

Every headline includes the audit window, discovered/included/excluded video counts, total/extracted/counted claims, result distribution, non-triggered and insufficient-data counts, scope categories, providers and proxies, model and methodology versions, limitations, relationship disclosure, and correction path.

Present the aggregate as “scenario-outcome alignment among counted, activated, verifiable claims.” Display the denominator near the percentage. Never imply viewer profits, trading performance, future accuracy, certification, or a guarantee.

## Public/private split

Private views may show full evidence paths and longer excerpts. Public views default to minimum necessary excerpts, escaped text, no local paths, no raw transcript download, no API cache, and no unauthenticated sensitive endpoint. Thumbnails, portraits, logos, and fonts require documented rights in `ASSET_LICENSES.yml`.

The JSON snapshot in `reports/dashboard_data.json` is an internal presentation artifact and can contain private detail used by the bilingual PDF. It is not the public API contract. `/api/dashboard` and the HTML page use a separate strict aggregate DTO. With `PUBLIC_CLAIM_LEDGER=false`, they never include claim text/excerpts, model reasoning, video URLs, local paths, or provider error strings. Private mode is labelled “Private preview”; public mode without a current accepted review is labelled “Human review pending.” In either state, report and claim-ledger downloads remain unavailable.

After the evidence review is accepted, inspect the regenerated dashboard, PDF, and any optional public claim ledger, then run `review publication-accept`. Public `finalize` requires that presentation checkpoint, verifies the completed final directory and ZIP, and only then activates a publication manifest bound to the accepted artifacts. The dashboard and each download compare the files they would serve with those activated hashes. A missing, regenerated, or replaced file fails closed instead of inheriting an earlier approval.

## Bilingual and accessible output

Language switching must change text, direction, number/date formatting where appropriate, labels, alt text, and downloadable report—not only navigation. Persian uses RTL layout while charts, hashes, symbols, timestamps, and code remain LTR. Respect reduced motion, keyboard navigation, contrast, semantic headings, and screen-reader labels.

The synthetic demo may be publicly shown only with its synthetic notice intact.

## Generate the bilingual PDF

After the `report` stage, generate and inspect the Persian-first, English-second document, accept the exact presentation artifacts, and then finalize so the PDF enters the hash-verifiable bundle:

```bash
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
# Inspect dashboard_data.json, the PDF, and any optional public ledger before continuing.
docker compose run --rm audit-lab python -m audit_lab.cli review publication-accept \
  --reviewer "Reviewer name" --notes "Dashboard, PDF, and optional public ledger checked"
docker compose run --rm audit-lab python -m audit_lab.cli finalize
docker compose run --rm audit-lab python -m audit_lab.cli verify-final
```

The stable output is `workspace/reports/audit-report.pdf`. It is a presentation view of `dashboard_data.json`; it does not recalculate or improve an audit result.

For a real public audit, accept the current evidence-review binding, regenerate `report`, generate and inspect the Persian-first/English-second PDF, inspect any optional public ledger, record `review publication-accept`, then finalize and verify without changing an accepted artifact. Evidence acceptance becomes stale whenever the collection, outcome, or scoring artifacts change. Running `report` again, regenerating the PDF, replacing the optional ledger, or changing either review ledger invalidates publication approval and the activated manifest; repeat `review publication-accept` and `finalize` before serving the dashboard or downloads.
