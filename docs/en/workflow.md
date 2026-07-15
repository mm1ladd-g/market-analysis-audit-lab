# Stage workflow and operator runbook

[English](workflow.md) · [فارسی](../fa/workflow.md) · [Documentation](index.md)

## Preflight

Record the operator, purpose, permitted sources, date boundary, timezone, categories, providers, expected video count, budget ceiling, review owner, retention period, `AUDIT_RELATIONSHIP_DISCLOSURE`, and `CORRECTION_CONTACT`. Back up an existing workspace before reuse.

```bash
python -m audit_lab.cli doctor
python -m audit_lab.cli smoke
python -m audit_lab.cli status
```

## Stages

1. `collect` records authorized source metadata and preferred captions. It must prove that scanning crossed `START_DATE` or exhausted the source.
2. `transcribe` optionally creates timed transcripts for missing captions from authorized audio when the fallback is explicitly enabled; raw audio is removed by default.
3. `manifest` rechecks channel/date/category/subtitle policy, normalizes transcripts, writes exclusions and SHA-256 inventories, and creates a versioned collection pack.
4. `verify` recomputes hashes and tests the ZIP. Stop on failure.
5. `extract-claims` selects falsifiable claims with source line ranges. Run `--limit 1`, review, then continue. `--force` spends again and creates new model evidence.
6. `fetch-outcomes` resolves supported assets, retrieves or imports market rows, records venue/interval/proxy status, and builds 24/48-hour windows.
7. `score` applies deterministic exclusions first, then uses the configured model only for remaining interpretation. Test one video before a full run.
8. `report` derives presentation JSON; it must not recompute scores.
9. For public release, accept the evidence review, rerun `report`, generate and inspect the PDF and optional public ledger, then run `review publication-accept` to bind those exact presentation artifacts.
10. `finalize` copies required components, methodology, reproduction files, and hash inventories into a complete bundle. In public mode it requires both current review checkpoints, verifies that directory and ZIP, and only then atomically activates a hash-bound publication manifest.
11. `verify-final` independently reopens and hashes the final directory and ZIP.

Use `python -m audit_lab.cli run --stop-after STAGE` only after understanding each stage; it does not replace checkpoints.

The public dashboard, PDF, and explicitly enabled claim ledger fail closed unless their current hashes match the activated publication manifest. After rerunning `report`, regenerating or replacing the PDF, changing either review ledger, or replacing the optional ledger, repeat `review publication-accept` and `finalize` before restoring public access.

## Failure recovery

Do not delete evidence to make a stage pass. Fix configuration or provider problems, preserve failure logs, and rerun the smallest affected stage. Cache keys prevent reuse after relevant transcript, prompt, schema, policy, model, or outcome changes. A hash mismatch means the artifact is untrusted until rebuilt or restored.

## Human checkpoints

Review collection completeness, exclusions, unknown categories, every new provider mapping, one extraction per language/content style, conditional triggers, counted denominator, proxy-sensitive decisions, conclusion wording, rights, privacy, and public excerpts. Record reviewer identity and correction path outside secrets.
