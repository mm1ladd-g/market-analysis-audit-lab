from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from audit_lab.settings import Settings
from audit_lab.utils.hash import sha256_bytes, sha256_json


PUBLICATION_SNAPSHOT_SCHEMA_VERSION = "public-artifact-set-v1"
PUBLICATION_BINDING_SCHEMA_VERSION = "publication-review-binding-v1"
PUBLICATION_MANIFEST_NAME = "publication_manifest.json"
REPORT_PRIORITY_NAMES = (
    "market_analysis_audit_report.pdf",
    "market_analysis_audit_full_report.pdf",
    "audit-report.pdf",
    "audit_report.pdf",
    "report.pdf",
)
SAFE_REPORT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.pdf")
CLAIM_ARTIFACT_PATHS = {
    "claims": "analysis/claims/claims.jsonl",
    "scores": "analysis/scores/scores.jsonl",
    "outcomes": "analysis/outcomes/claim_outcomes.json",
}
CLAIM_BINDING_KEYS = {
    "claims": "claims_ledger_sha256",
    "scores": "scoring_ledger_sha256",
    "outcomes": "outcome_artifact_sha256",
}


def publication_manifest_path(settings: Settings) -> Path:
    return settings.reports_dir / PUBLICATION_MANIFEST_NAME


def invalidate_publication_snapshot(settings: Settings) -> None:
    publication_manifest_path(settings).unlink(missing_ok=True)


def _artifact_record(path: Path, public_path: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"Cannot publish; required artifact is unreadable: {path.name}") from exc
    return {
        "path": public_path,
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def find_report(reports_dir: Path) -> Path | None:
    if not reports_dir.is_dir():
        return None
    root = reports_dir.resolve()
    candidates = [reports_dir / name for name in REPORT_PRIORITY_NAMES]
    candidates.extend(sorted(reports_dir.glob("*.pdf")))
    seen: set[Path] = set()
    for candidate in candidates:
        if not SAFE_REPORT_NAME.fullmatch(candidate.name):
            continue
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def build_publication_binding(
    settings: Settings,
    evidence_review_binding: dict[str, Any],
) -> dict[str, Any]:
    evidence_binding = dict(evidence_review_binding)
    evidence_hash = evidence_binding.get("binding_sha256")
    evidence_core = dict(evidence_binding)
    evidence_core.pop("binding_sha256", None)
    if (
        settings.publication_mode != "public"
        or evidence_binding.get("publication_mode") != "public"
        or not isinstance(evidence_hash, str)
        or sha256_json(evidence_core) != evidence_hash
    ):
        raise SystemExit("Publication review requires a valid accepted evidence binding.")

    dashboard_path = settings.reports_dir / "dashboard_data.json"
    report_path = find_report(settings.reports_dir)
    artifacts: dict[str, Any] = {
        "dashboard": _artifact_record(dashboard_path, "dashboard_data.json"),
        "report": (
            _artifact_record(report_path, report_path.name) if report_path is not None else None
        ),
        "claim_ledger": None,
    }
    if settings.public_claim_ledger:
        paths = {
            "claims": settings.claims_dir / "claims.jsonl",
            "scores": settings.scores_dir / "scores.jsonl",
            "outcomes": settings.outcomes_dir / "claim_outcomes.json",
        }
        records = {
            role: _artifact_record(path, CLAIM_ARTIFACT_PATHS[role])
            for role, path in paths.items()
        }
        for role, record in records.items():
            if record["sha256"] != evidence_binding.get(CLAIM_BINDING_KEYS[role]):
                raise SystemExit(
                    f"Publication review requires {role} to match the accepted evidence."
                )
        artifacts["claim_ledger"] = records

    try:
        dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Publication review requires a readable dashboard_data.json.") from exc
    human_review = dashboard.get("human_review") if isinstance(dashboard, dict) else None
    publication = dashboard.get("publication") if isinstance(dashboard, dict) else None
    if not (
        isinstance(dashboard, dict)
        and dashboard.get("collection_id") == evidence_binding.get("collection_id")
        and isinstance(human_review, dict)
        and human_review.get("accepted_for_current_artifacts") is True
        and human_review.get("binding_sha256") == evidence_hash
        and isinstance(publication, dict)
        and publication.get("mode") == "public"
        and publication.get("ready") is True
        and bool(publication.get("public_claim_ledger")) == settings.public_claim_ledger
    ):
        raise SystemExit(
            "Publication review requires a dashboard regenerated after evidence acceptance."
        )

    binding: dict[str, Any] = {
        "schema_version": PUBLICATION_BINDING_SCHEMA_VERSION,
        "publication_mode": "public",
        "collection_id": evidence_binding.get("collection_id"),
        "evidence_review_binding_sha256": evidence_hash,
        "public_claim_ledger": settings.public_claim_ledger,
        "artifacts": artifacts,
    }
    binding["binding_sha256"] = sha256_json(binding)
    return binding


def build_publication_snapshot(
    *,
    reports_dir: Path,
    claims_path: Path,
    scores_path: Path,
    outcomes_path: Path,
    evidence_review_binding: dict[str, Any],
    publication_binding: dict[str, Any],
    publication_event_sha256: str,
    publication_reviewed_at_utc: str | None,
) -> dict[str, Any]:
    evidence_binding = dict(evidence_review_binding)
    evidence_hash = evidence_binding.get("binding_sha256")
    evidence_core = dict(evidence_binding)
    evidence_core.pop("binding_sha256", None)
    if (
        evidence_binding.get("publication_mode") != "public"
        or not isinstance(evidence_hash, str)
        or sha256_json(evidence_core) != evidence_hash
    ):
        raise SystemExit("Cannot publish; the accepted evidence-review binding is invalid.")

    binding = dict(publication_binding)
    binding_hash = binding.get("binding_sha256")
    binding_core = dict(binding)
    binding_core.pop("binding_sha256", None)
    if not (
        binding.get("schema_version") == PUBLICATION_BINDING_SCHEMA_VERSION
        and binding.get("publication_mode") == "public"
        and binding.get("collection_id") == evidence_binding.get("collection_id")
        and binding.get("evidence_review_binding_sha256") == evidence_hash
        and isinstance(binding_hash, str)
        and sha256_json(binding_core) == binding_hash
    ):
        raise SystemExit("Cannot publish; the publication-review binding is invalid.")

    artifacts = binding.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SystemExit("Cannot publish; the publication artifact register is invalid.")
    dashboard_bytes = _read_verified_artifact(
        reports_dir / "dashboard_data.json",
        artifacts.get("dashboard"),
        expected_public_path="dashboard_data.json",
    )
    if dashboard_bytes is None:
        raise SystemExit("Cannot publish; dashboard changed after publication acceptance.")
    report_record = artifacts.get("report")
    if report_record is not None:
        report_name = report_record.get("path") if isinstance(report_record, dict) else None
        if not isinstance(report_name, str) or not SAFE_REPORT_NAME.fullmatch(report_name):
            raise SystemExit("Cannot publish; the accepted report record is invalid.")
        if _read_verified_artifact(
            reports_dir / report_name, report_record, expected_public_path=report_name
        ) is None:
            raise SystemExit("Cannot publish; PDF changed after publication acceptance.")

    public_claim_ledger = bool(binding.get("public_claim_ledger"))
    ledger_records = artifacts.get("claim_ledger")
    if public_claim_ledger:
        if not isinstance(ledger_records, dict):
            raise SystemExit("Cannot publish; the accepted claim-ledger register is invalid.")
        ledger_paths = {"claims": claims_path, "scores": scores_path, "outcomes": outcomes_path}
        for role, path in ledger_paths.items():
            record = ledger_records.get(role)
            if (
                not isinstance(record, dict)
                or record.get("sha256") != evidence_binding.get(CLAIM_BINDING_KEYS[role])
                or _read_verified_artifact(
                    path, record, expected_public_path=CLAIM_ARTIFACT_PATHS[role]
                )
                is None
            ):
                raise SystemExit(
                    f"Cannot publish; {role} ledger changed after publication acceptance."
                )
    elif ledger_records is not None:
        raise SystemExit("Cannot publish; unexpected claim-ledger artifacts were registered.")

    snapshot: dict[str, Any] = {
        "schema_version": PUBLICATION_SNAPSHOT_SCHEMA_VERSION,
        "collection_id": evidence_binding.get("collection_id"),
        "publication_review": {
            "status": "accepted",
            "event_sha256": publication_event_sha256,
            "reviewed_at_utc": publication_reviewed_at_utc,
            "binding_sha256": binding_hash,
        },
        "evidence_review_binding": evidence_binding,
        "publication_binding": binding,
        "public_claim_ledger": public_claim_ledger,
        "artifacts": artifacts,
    }
    snapshot["snapshot_sha256"] = sha256_json(snapshot)
    return snapshot


def _read_verified_artifact(
    path: Path,
    record: Any,
    *,
    expected_public_path: str,
) -> bytes | None:
    if not isinstance(record, dict) or record.get("path") != expected_public_path:
        return None
    expected_hash = record.get("sha256")
    expected_size = record.get("size_bytes")
    if not isinstance(expected_hash, str) or not isinstance(expected_size, int):
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if len(payload) != expected_size or sha256_bytes(payload) != expected_hash:
        return None
    return payload


def load_verified_publication_snapshot(settings: Settings) -> dict[str, Any] | None:
    if settings.publication_mode != "public":
        return None
    try:
        manifest = json.loads(publication_manifest_path(settings).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    recorded_snapshot_hash = manifest.get("snapshot_sha256")
    manifest_core = dict(manifest)
    manifest_core.pop("snapshot_sha256", None)
    if (
        manifest.get("schema_version") != PUBLICATION_SNAPSHOT_SCHEMA_VERSION
        or not isinstance(recorded_snapshot_hash, str)
        or sha256_json(manifest_core) != recorded_snapshot_hash
    ):
        return None

    review = manifest.get("publication_review")
    evidence_binding = manifest.get("evidence_review_binding")
    binding = manifest.get("publication_binding")
    artifacts = manifest.get("artifacts")
    if not isinstance(review, dict) or review.get("status") != "accepted":
        return None
    if not isinstance(review.get("event_sha256"), str):
        return None
    if (
        not isinstance(evidence_binding, dict)
        or not isinstance(binding, dict)
        or not isinstance(artifacts, dict)
    ):
        return None
    evidence_hash = evidence_binding.get("binding_sha256")
    evidence_core = dict(evidence_binding)
    evidence_core.pop("binding_sha256", None)
    if (
        evidence_binding.get("publication_mode") != "public"
        or evidence_binding.get("collection_id") != manifest.get("collection_id")
        or not isinstance(evidence_hash, str)
        or sha256_json(evidence_core) != evidence_hash
    ):
        return None
    binding_hash = binding.get("binding_sha256")
    binding_core = dict(binding)
    binding_core.pop("binding_sha256", None)
    if (
        binding.get("schema_version") != PUBLICATION_BINDING_SCHEMA_VERSION
        or binding.get("publication_mode") != "public"
        or binding.get("collection_id") != manifest.get("collection_id")
        or binding.get("evidence_review_binding_sha256") != evidence_hash
        or review.get("binding_sha256") != binding_hash
        or not isinstance(binding_hash, str)
        or sha256_json(binding_core) != binding_hash
        or binding.get("artifacts") != artifacts
        or bool(binding.get("public_claim_ledger"))
        != bool(manifest.get("public_claim_ledger"))
    ):
        return None

    dashboard_bytes = _read_verified_artifact(
        settings.reports_dir / "dashboard_data.json",
        artifacts.get("dashboard"),
        expected_public_path="dashboard_data.json",
    )
    if dashboard_bytes is None:
        return None
    try:
        dashboard = json.loads(dashboard_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    dashboard_review = dashboard.get("human_review") if isinstance(dashboard, dict) else None
    dashboard_publication = dashboard.get("publication") if isinstance(dashboard, dict) else None
    if not (
        isinstance(dashboard, dict)
        and dashboard.get("collection_id") == manifest.get("collection_id")
        and isinstance(dashboard_review, dict)
        and dashboard_review.get("accepted_for_current_artifacts") is True
        and dashboard_review.get("binding_sha256") == evidence_hash
        and isinstance(dashboard_publication, dict)
        and dashboard_publication.get("mode") == "public"
        and dashboard_publication.get("ready") is True
        and bool(dashboard_publication.get("public_claim_ledger"))
        == bool(manifest.get("public_claim_ledger"))
    ):
        return None

    report_record = artifacts.get("report")
    if report_record is not None:
        report_name = report_record.get("path") if isinstance(report_record, dict) else None
        if not isinstance(report_name, str) or not SAFE_REPORT_NAME.fullmatch(report_name):
            return None
    ledger_records = artifacts.get("claim_ledger")
    if manifest.get("public_claim_ledger"):
        if not isinstance(ledger_records, dict):
            return None
        for role, public_path in CLAIM_ARTIFACT_PATHS.items():
            record = ledger_records.get(role)
            if (
                not isinstance(record, dict)
                or record.get("path") != public_path
                or record.get("sha256") != evidence_binding.get(CLAIM_BINDING_KEYS[role])
            ):
                return None
    elif ledger_records is not None:
        return None
    snapshot = {"manifest": manifest, "dashboard": dashboard}
    verified_report = read_verified_report(settings, snapshot)
    if report_record is not None and verified_report is None:
        return None
    verified_claims = read_verified_claim_artifacts(settings, snapshot)
    if manifest.get("public_claim_ledger") and verified_claims is None:
        return None
    snapshot["report"] = verified_report
    snapshot["claim_artifacts"] = verified_claims
    return snapshot


def read_verified_report(
    settings: Settings,
    snapshot: dict[str, Any],
) -> tuple[bytes, str] | None:
    record = snapshot["manifest"]["artifacts"].get("report")
    if not isinstance(record, dict):
        return None
    name = record.get("path")
    if not isinstance(name, str) or not SAFE_REPORT_NAME.fullmatch(name):
        return None
    payload = _read_verified_artifact(
        settings.reports_dir / name,
        record,
        expected_public_path=name,
    )
    return (payload, name) if payload is not None else None


def read_verified_claim_artifacts(
    settings: Settings,
    snapshot: dict[str, Any],
) -> dict[str, bytes] | None:
    manifest = snapshot["manifest"]
    if not settings.public_claim_ledger or not manifest.get("public_claim_ledger"):
        return None
    records = manifest["artifacts"].get("claim_ledger")
    if not isinstance(records, dict):
        return None
    paths = {
        "claims": settings.claims_dir / "claims.jsonl",
        "scores": settings.scores_dir / "scores.jsonl",
        "outcomes": settings.outcomes_dir / "claim_outcomes.json",
    }
    payloads: dict[str, bytes] = {}
    for role, path in paths.items():
        payload = _read_verified_artifact(
            path,
            records.get(role),
            expected_public_path=CLAIM_ARTIFACT_PATHS[role],
        )
        if payload is None:
            return None
        payloads[role] = payload
    return payloads
