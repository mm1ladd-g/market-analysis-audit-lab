# Fairness, corrections, and right of reply

[English](fairness-and-publication.md) · [فارسی](../fa/fairness-and-publication.md) · [Documentation](index.md)

## Before analysis

Freeze the subject/channel, inclusive window, category scope, inclusion rules, providers, proxies, scoring policy, maturity window, and known conflicts. Declare whether the work is independent, commissioned, sponsored, promotional, or performed for the subject. Do not change scope after seeing results without publishing both versions and the reason.

## Before publication

- Verify collection and final hashes.
- Review exclusions, unknown categories, conditional triggers, invalidations, multi-leg ordering, proxy-sensitive results, denominator arithmetic, translations, and excerpts.
- Identify the human reviewer and methodology/model/provider versions.
- Separate evidence findings from promotional opinion.
- State that the audit does not establish profit, subscriber outcomes, future performance, or total analyst competence.
- Use the minimum necessary source excerpt and confirm asset rights.
- Give the named subject a reasonable opportunity to review factual source errors and provide a response without granting control over methodology.

## Hash-bound human checkpoint

`PUBLICATION_MODE=public` is a technical gate, not a fairness conclusion. After reviewing the evidence and presentation, a named human must record an explicit checkpoint:

```bash
docker compose run --rm audit-lab python -m audit_lab.cli review status
docker compose run --rm audit-lab python -m audit_lab.cli review accept \
  --reviewer "Reviewer name" --notes "Scope, excerpts, translations, denominator, and limitations checked"
docker compose run --rm audit-lab python -m audit_lab.cli report
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
# Inspect dashboard_data.json, the PDF, and any optional public ledger before continuing.
docker compose run --rm audit-lab python -m audit_lab.cli review publication-accept \
  --reviewer "Reviewer name" --notes "Dashboard, PDF, and optional public ledger checked"
docker compose run --rm audit-lab python -m audit_lab.cli finalize
docker compose run --rm audit-lab python -m audit_lab.cli verify-final
```

The append-only review ledger hash-chains its events and binds acceptance to public mode, the collection manifest, claim ledger, outcome snapshot/artifact, scoring run, and score ledger. Changing mode or any bound artifact makes acceptance stale. Use `review revoke` to withdraw publication approval; never edit the ledger by hand. Reviewer identity and notes stay in the private audit bundle and are not returned by the public dashboard DTO.

After the evidence checkpoint, regenerate and inspect the dashboard, PDF, and any explicitly enabled public claim ledger. `review publication-accept` records a second, hash-bound checkpoint for exactly those presentation artifacts. In public mode, `finalize` requires both checkpoints, verifies the newly built final directory and ZIP, and only then activates the publication manifest. The public dashboard and downloads are served only while their current bytes match that manifest. Replacing or deleting a published artifact fails closed. Running `report` again, regenerating the PDF, or changing either review ledger requires a new `review publication-accept` followed by another successful `finalize` before publication can resume.

## Corrections

Publish a visible correction contact, immutable audit ID, date, version, and changelog. Classify a correction as source/metadata, transcript, market data, claim extraction, scoring, translation, or presentation. Never overwrite a released bundle silently: issue a new version, preserve the prior hash, explain impact on claims/denominator/headline, and link versions.

Good-faith criticism or reply is not automatically a scoring change. Evidence errors are. Retaliation, harassment, engagement manipulation, selective deletion, and hidden paid relationships are prohibited.
