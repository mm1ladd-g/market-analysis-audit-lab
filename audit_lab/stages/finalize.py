from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from audit_lab import __version__
from audit_lab.publication import (
    PUBLICATION_MANIFEST_NAME,
    build_publication_binding,
    build_publication_snapshot,
    invalidate_publication_snapshot,
)
from audit_lab.settings import Settings
from audit_lab.stages.extract_claims import CLAIM_SCHEMA_VERSION, EVIDENCE_POLICY
from audit_lab.stages.score_claims import (
    SCORING_POLICY,
    SCORING_SCHEMA_VERSION,
    scoring_input_fingerprint,
    validate_score_artifact,
)
from audit_lab.stages.verify import verify_audit_pack
from audit_lab.utils.hash import sha256_file, sha256_json
from audit_lab.utils.jsonio import write_json_atomic


REVIEW_SCHEMA_VERSION = "human-review-v1"
PUBLICATION_REVIEW_SCHEMA_VERSION = "publication-review-v1"
FINAL_BUNDLE_SCHEMA_VERSION = "final-audit-v2"
COUNTED_RESULTS = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read required JSON artifact {path.name}: {exc}") from None
    if not isinstance(payload, dict):
        raise SystemExit(f"Required JSON artifact must contain an object: {path.name}")
    return payload


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("row is not an object")
            rows.append(row)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"Cannot read {path.name} as JSONL: {exc}") from None
    return rows


def _workspace_file(settings: Settings, relative_path: str, *, label: str) -> Path:
    value = Path(relative_path)
    if value.is_absolute():
        raise SystemExit(f"Cannot finalize; {label} must be workspace-relative.")
    root = settings.workspace_dir.resolve()
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise SystemExit(f"Cannot finalize; {label} escapes the workspace.") from None
    return candidate


def _assert_unique(rows: list[dict], key: str, *, label: str) -> dict[str, dict]:
    values: dict[str, dict] = {}
    for row in rows:
        identifier = row.get(key)
        if not isinstance(identifier, str) or not identifier:
            raise SystemExit(f"Cannot finalize; {label} contains a row without {key}.")
        if identifier in values:
            raise SystemExit(f"Cannot finalize; duplicate {key} in {label}: {identifier}")
        values[identifier] = row
    return values


def _same_rows(left: dict[str, dict], right: dict[str, dict]) -> bool:
    return left.keys() == right.keys() and all(
        sha256_json(left[key]) == sha256_json(right[key]) for key in left
    )


def _score_aggregate(scores: list[dict]) -> dict:
    counts = Counter(score.get("result") for score in scores)
    counted = [score for score in scores if score.get("counts_in_final_score")]
    final_score = None
    if counted:
        final_score = round(sum(float(score.get("score", 0)) for score in counted) / len(counted) * 100, 2)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for score in scores:
        by_category[str(score.get("category"))].append(score)
    category_breakdown = {}
    for category, rows in sorted(by_category.items()):
        category_counted = [row for row in rows if row.get("counts_in_final_score")]
        category_breakdown[category] = {
            "total_claims": len(rows),
            "counted_claims": len(category_counted),
            "score": (
                None
                if not category_counted
                else round(
                    sum(float(row.get("score", 0)) for row in category_counted)
                    / len(category_counted)
                    * 100,
                    2,
                )
            ),
            "results": dict(Counter(row.get("result") for row in rows)),
        }
    return {
        "total_claims": len(scores),
        "counted_claims": len(counted),
        "final_score": final_score,
        "results": dict(counts),
        "category_breakdown": category_breakdown,
    }


def _validate_outcome_hashes(outcomes: dict, *, allow_legacy_synthetic: bool = False) -> None:
    recorded_outcome_hash = outcomes.get("outcome_snapshot_sha256")
    unhashed = dict(outcomes)
    unhashed.pop("outcome_snapshot_sha256", None)
    if not isinstance(recorded_outcome_hash, str) or sha256_json(unhashed) != recorded_outcome_hash:
        raise SystemExit("Cannot finalize; the outcome snapshot hash does not match its payload.")

    expected_market_hash = sha256_json({
        "collection_id": outcomes.get("collection_id"),
        "scope": outcomes.get("audit_scope_categories"),
        "series": outcomes.get("series", {}),
        "claims": outcomes.get("claims", []),
    })
    recorded_market_hash = outcomes.get("market_evidence_snapshot_sha256")
    if recorded_market_hash != expected_market_hash and allow_legacy_synthetic:
        legacy_payload = dict(outcomes)
        legacy_payload.pop("outcome_snapshot_sha256", None)
        legacy_payload.pop("market_evidence_snapshot_sha256", None)
        expected_market_hash = sha256_json(legacy_payload)
    if recorded_market_hash != expected_market_hash:
        raise SystemExit("Cannot finalize; the market-evidence aggregate hash does not match its payload.")


def _validate_market_source_hashes(settings: Settings, outcomes: dict) -> int:
    synthetic_private_demo = bool(outcomes.get("synthetic_demo")) and settings.publication_mode == "private"
    checked: set[tuple[str, str]] = set()
    candidates: list[dict] = [
        item for item in outcomes.get("series", {}).values() if isinstance(item, dict)
    ]
    for claim in outcomes.get("claims", []):
        if not isinstance(claim, dict):
            continue
        candidates.extend(
            item for item in claim.get("assets", [])
            if isinstance(item, dict) and item.get("status") == "available"
        )
    for item in candidates:
        source_file = item.get("source_file")
        source_hash = item.get("source_sha256")
        if not source_file and not source_hash:
            continue
        if not isinstance(source_file, str) or not isinstance(source_hash, str):
            raise SystemExit("Cannot finalize; market evidence has an incomplete source-hash record.")
        marker = (source_file, source_hash)
        if marker in checked:
            continue
        checked.add(marker)
        path = _workspace_file(settings, source_file, label="market source_file")
        if not path.is_file() or sha256_file(path) != source_hash:
            if synthetic_private_demo:
                continue
            raise SystemExit(f"Cannot finalize; market source hash failed for {Path(source_file).name}.")
    return len(checked)


def validate_analysis_artifacts(settings: Settings, *, require_dashboard: bool = True) -> dict:
    """Recompute cross-stage ledgers and aggregates before review or finalization."""
    paths = {
        "manifest": settings.pack_dir / "manifest.json",
        "collection_summary": settings.pack_dir / "run_summary.json",
        "claims_summary": settings.claims_dir / "extraction_run.json",
        "claims": settings.claims_dir / "claims.jsonl",
        "outcomes": settings.outcomes_dir / "claim_outcomes.json",
        "scores_summary": settings.scores_dir / "scoring_run.json",
        "scores": settings.scores_dir / "scores.jsonl",
    }
    if require_dashboard:
        paths["dashboard"] = settings.reports_dir / "dashboard_data.json"
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise SystemExit("Cannot finalize; missing artifacts: " + ", ".join(missing))

    manifest = _read_json(paths["manifest"])
    collection_summary = _read_json(paths["collection_summary"])
    claims_summary = _read_json(paths["claims_summary"])
    outcomes = _read_json(paths["outcomes"])
    scores_summary = _read_json(paths["scores_summary"])
    collection_id = manifest.get("collection_id")
    if not isinstance(collection_id, str) or not collection_id:
        raise SystemExit("Cannot finalize; manifest collection_id is missing.")
    if collection_summary.get("collection_id") != collection_id:
        raise SystemExit("Cannot finalize; collection summary does not match the manifest.")
    for name, payload in (("claims", claims_summary), ("scores", scores_summary)):
        if payload.get("collection_id") != collection_id or payload.get("status") != "complete":
            raise SystemExit(f"Cannot finalize; {name} stage is not complete for this collection.")
    if outcomes.get("collection_id") != collection_id:
        raise SystemExit("Cannot finalize; outcome evidence does not belong to this collection.")
    if set(
        claims_summary.get("audit_scope_categories", settings.audit_scope_categories)
    ) != set(settings.audit_scope_categories):
        raise SystemExit("Cannot finalize; extraction scope differs from current runtime scope.")
    if set(
        scores_summary.get("audit_scope_categories", settings.audit_scope_categories)
    ) != set(settings.audit_scope_categories):
        raise SystemExit("Cannot finalize; scoring scope differs from current runtime scope.")
    synthetic_private_demo = (
        settings.publication_mode == "private"
        and bool(claims_summary.get("synthetic_demo"))
        and bool(outcomes.get("synthetic_demo"))
        and bool(scores_summary.get("synthetic_demo"))
    )
    if not synthetic_private_demo and (
        claims_summary.get("schema_version") != CLAIM_SCHEMA_VERSION
        or claims_summary.get("evidence_policy") != EVIDENCE_POLICY
    ):
        raise SystemExit("Cannot finalize; extraction schema or evidence policy is not current.")
    if not synthetic_private_demo and (
        scores_summary.get("schema_version") != SCORING_SCHEMA_VERSION
        or scores_summary.get("scoring_policy") != SCORING_POLICY
    ):
        raise SystemExit("Cannot finalize; scoring schema or policy is not current.")

    pack_verification = verify_audit_pack(settings)
    if not pack_verification.get("verified"):
        raise SystemExit("Cannot finalize; collection evidence verification failed.")

    scoped_videos = {
        video.get("video_id"): video
        for video in manifest.get("videos", [])
        if isinstance(video, dict)
        and video.get("video_id")
        and video.get("transcript_txt")
        and video.get("category") in set(settings.audit_scope_categories)
    }
    if int(claims_summary.get("eligible_videos", -1)) != len(scoped_videos):
        raise SystemExit("Cannot finalize; extraction eligible-video aggregate is inconsistent.")

    artifact_claim_rows: list[dict] = []
    for video_id, video in scoped_videos.items():
        artifact_path = settings.claims_dir / f"{video_id}.claims.json"
        if not artifact_path.is_file():
            raise SystemExit(f"Cannot finalize; per-video claim artifact is missing for {video_id}.")
        artifact = _read_json(artifact_path)
        if artifact.get("collection_id") != collection_id or artifact.get("video_id") != video_id:
            raise SystemExit(f"Cannot finalize; per-video claim artifact binding failed for {video_id}.")
        if not synthetic_private_demo and (
            artifact.get("schema_version") != CLAIM_SCHEMA_VERSION
            or artifact.get("evidence_policy") != EVIDENCE_POLICY
        ):
            raise SystemExit(f"Cannot finalize; per-video claim policy is stale for {video_id}.")
        if artifact.get("transcript_sha256") != video.get("transcript_sha256"):
            raise SystemExit(f"Cannot finalize; claim transcript hash binding failed for {video_id}.")
        transcript = _workspace_file(settings, str(video.get("transcript_txt") or ""), label="transcript_txt")
        if not transcript.is_file() or sha256_file(transcript) != video.get("transcript_sha256"):
            raise SystemExit(f"Cannot finalize; canonical transcript hash failed for {video_id}.")
        claims = artifact.get("claims")
        if not isinstance(claims, list):
            raise SystemExit(f"Cannot finalize; per-video claims are malformed for {video_id}.")
        for claim in claims:
            if not isinstance(claim, dict) or claim.get("video_id") != video_id:
                raise SystemExit(f"Cannot finalize; claim/video binding failed for {video_id}.")
            if claim.get("transcript_sha256") != video.get("transcript_sha256"):
                raise SystemExit(f"Cannot finalize; claim/source hash binding failed for {video_id}.")
        artifact_claim_rows.extend(claims)

    if int(claims_summary.get("completed_videos", -1)) != len(scoped_videos):
        raise SystemExit("Cannot finalize; extraction completed-video aggregate is inconsistent.")
    claim_ledger_rows = _read_jsonl(paths["claims"])
    artifact_claims = _assert_unique(artifact_claim_rows, "claim_id", label="per-video claim artifacts")
    claim_ledger = _assert_unique(claim_ledger_rows, "claim_id", label="claim ledger")
    if not _same_rows(artifact_claims, claim_ledger):
        raise SystemExit("Cannot finalize; aggregate claim ledger differs from per-video artifacts.")
    extraction_counts = {
        "total_claims": len(claim_ledger_rows),
        "scoreable_claims": sum(row.get("scoreability") == "scoreable" for row in claim_ledger_rows),
        "conditional_claims": sum(
            row.get("scoreability") == "conditional_scoreable" for row in claim_ledger_rows
        ),
        "not_scoreable_claims": sum(
            row.get("scoreability") == "not_scoreable" for row in claim_ledger_rows
        ),
    }
    if any(claims_summary.get(key) != value for key, value in extraction_counts.items()):
        raise SystemExit("Cannot finalize; extraction summary aggregates do not match the claim ledger.")

    outcome_rows = outcomes.get("claims")
    if not isinstance(outcome_rows, list):
        raise SystemExit("Cannot finalize; outcome claim ledger is malformed.")
    outcome_ledger = _assert_unique(outcome_rows, "claim_id", label="outcome ledger")
    if outcome_ledger.keys() != claim_ledger.keys():
        raise SystemExit("Cannot finalize; outcome ledger does not cover every extracted claim exactly once.")
    _validate_outcome_hashes(outcomes, allow_legacy_synthetic=synthetic_private_demo)
    market_source_hash_count = _validate_market_source_hashes(settings, outcomes)

    if int(scores_summary.get("eligible_videos", -1)) != len(scoped_videos):
        raise SystemExit("Cannot finalize; scoring eligible-video aggregate is inconsistent.")
    artifact_score_rows: list[dict] = []
    scoring_fingerprints: list[str] = []
    for video_id in scoped_videos:
        artifact_path = settings.scores_dir / f"{video_id}.scores.json"
        if not artifact_path.is_file():
            raise SystemExit(f"Cannot finalize; per-video score artifact is missing for {video_id}.")
        artifact = _read_json(artifact_path)
        if artifact.get("collection_id") != collection_id or artifact.get("video_id") != video_id:
            raise SystemExit(f"Cannot finalize; per-video score artifact binding failed for {video_id}.")
        video_claims = [row for row in artifact_claim_rows if row.get("video_id") == video_id]
        video_outcomes = [outcome_ledger[row["claim_id"]] for row in video_claims]
        if not synthetic_private_demo:
            expected_fingerprint = scoring_input_fingerprint(
                settings=settings,
                prompt_sha256=str(scores_summary.get("prompt_sha256") or ""),
                video=scoped_videos[video_id],
                claims=video_claims,
                outcomes=video_outcomes,
            )
            if (
                artifact.get("schema_version") != SCORING_SCHEMA_VERSION
                or artifact.get("scoring_policy") != SCORING_POLICY
                or artifact.get("scoring_input_fingerprint") != expected_fingerprint
            ):
                raise SystemExit(f"Cannot finalize; score fingerprint or policy is stale for {video_id}.")
            try:
                validate_score_artifact(
                    artifact,
                    scoped_videos[video_id],
                    video_claims,
                    {item["claim_id"]: item for item in video_outcomes},
                )
            except (ValueError, TypeError) as exc:
                raise SystemExit(f"Cannot finalize; score contract failed for {video_id}: {exc}") from None
            scoring_fingerprints.append(expected_fingerprint)
        rows = artifact.get("scores")
        if not isinstance(rows, list):
            raise SystemExit(f"Cannot finalize; per-video scores are malformed for {video_id}.")
        for row in rows:
            if not isinstance(row, dict) or row.get("video_id") != video_id:
                raise SystemExit(f"Cannot finalize; score/video binding failed for {video_id}.")
        artifact_score_rows.extend(rows)
    if int(scores_summary.get("completed_videos", -1)) != len(scoped_videos):
        raise SystemExit("Cannot finalize; scoring completed-video aggregate is inconsistent.")
    score_ledger_rows = _read_jsonl(paths["scores"])
    artifact_scores = _assert_unique(artifact_score_rows, "claim_id", label="per-video score artifacts")
    score_ledger = _assert_unique(score_ledger_rows, "claim_id", label="score ledger")
    if not _same_rows(artifact_scores, score_ledger):
        raise SystemExit("Cannot finalize; aggregate score ledger differs from per-video artifacts.")
    if score_ledger.keys() != claim_ledger.keys():
        raise SystemExit("Cannot finalize; score ledger does not cover every extracted claim exactly once.")
    for claim_id, score in score_ledger.items():
        if score.get("video_id") != claim_ledger[claim_id].get("video_id"):
            raise SystemExit(f"Cannot finalize; score/claim video binding failed for {claim_id}.")
        result = score.get("result")
        counted = bool(score.get("counts_in_final_score"))
        numeric_score = float(score.get("score", 0))
        if counted and (result not in COUNTED_RESULTS or numeric_score != COUNTED_RESULTS[result]):
            raise SystemExit(f"Cannot finalize; counted-score contract failed for {claim_id}.")
        if not counted and numeric_score != 0:
            raise SystemExit(f"Cannot finalize; excluded score carries points for {claim_id}.")
    aggregate = _score_aggregate(score_ledger_rows)
    if any(scores_summary.get(key) != value for key, value in aggregate.items()):
        raise SystemExit("Cannot finalize; scoring summary aggregates do not match the score ledger.")

    return {
        "paths": paths,
        "manifest": manifest,
        "collection_summary": collection_summary,
        "claims_summary": claims_summary,
        "outcomes": outcomes,
        "scores_summary": scores_summary,
        "collection_id": collection_id,
        "pack_verification": pack_verification,
        "claim_count": len(claim_ledger_rows),
        "score_count": len(score_ledger_rows),
        "market_source_hash_count": market_source_hash_count,
        "scoring_fingerprints_sha256": sha256_json(sorted(scoring_fingerprints)),
        "synthetic_private_demo": synthetic_private_demo,
    }


def current_review_binding(settings: Settings) -> dict:
    required = {
        "manifest": settings.pack_dir / "manifest.json",
        "claims_summary": settings.claims_dir / "extraction_run.json",
        "claims_ledger": settings.claims_dir / "claims.jsonl",
        "outcomes": settings.outcomes_dir / "claim_outcomes.json",
        "scoring_summary": settings.scores_dir / "scoring_run.json",
        "scoring_ledger": settings.scores_dir / "scores.jsonl",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise SystemExit("Human review requires complete artifacts: " + ", ".join(missing))
    manifest = _read_json(required["manifest"])
    outcomes = _read_json(required["outcomes"])
    scoring = _read_json(required["scoring_summary"])
    binding = {
        "publication_mode": settings.publication_mode,
        "collection_id": manifest.get("collection_id"),
        "collection_manifest_sha256": sha256_file(required["manifest"]),
        "claims_summary_sha256": sha256_file(required["claims_summary"]),
        "claims_ledger_sha256": sha256_file(required["claims_ledger"]),
        "outcome_snapshot_sha256": outcomes.get("outcome_snapshot_sha256"),
        "outcome_artifact_sha256": sha256_file(required["outcomes"]),
        "scoring_run_sha256": sha256_file(required["scoring_summary"]),
        "scoring_ledger_sha256": sha256_file(required["scoring_ledger"]),
        "scoring_run_id": scoring.get("scoring_run_id"),
    }
    binding["binding_sha256"] = sha256_json(binding)
    return binding


def _validate_review_events(
    payload: dict,
    *,
    schema_version: str = REVIEW_SCHEMA_VERSION,
) -> tuple[bool, str | None]:
    if payload.get("schema_version") != schema_version:
        return False, "unsupported_schema"
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return False, "empty_ledger"
    previous_hash = None
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("sequence") != index:
            return False, "invalid_sequence"
        if event.get("previous_event_sha256") != previous_hash:
            return False, "broken_hash_chain"
        event_core = dict(event)
        recorded_hash = event_core.pop("event_sha256", None)
        if not isinstance(recorded_hash, str) or sha256_json(event_core) != recorded_hash:
            return False, "event_hash_mismatch"
        previous_hash = recorded_hash
    if payload.get("head_event_sha256") != previous_hash:
        return False, "head_hash_mismatch"
    return True, None


def get_human_review_status(settings: Settings) -> dict:
    path = settings.human_review_ledger_path
    if not path.is_file():
        return {
            "status": "not_reviewed",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "invalid",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
            "reason": "unreadable_ledger",
        }
    if not isinstance(payload, dict):
        return {
            "status": "invalid",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
            "reason": "invalid_ledger",
        }
    ledger_valid, reason = _validate_review_events(payload)
    if not ledger_valid:
        return {
            "status": "invalid",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
            "reason": reason,
        }
    latest = payload["events"][-1]
    try:
        current = current_review_binding(settings)
    except SystemExit:
        current = None
    binding_matches = bool(
        current
        and latest.get("binding", {}).get("binding_sha256")
        == current.get("binding_sha256")
    )
    accepted = latest.get("action") == "accepted" and binding_matches
    if latest.get("action") == "revoked":
        status = "revoked"
    elif not binding_matches:
        status = "stale"
    elif accepted:
        status = "accepted"
    else:
        status = "not_reviewed"
    return {
        "status": status,
        "ledger_valid": True,
        "accepted_for_current_artifacts": accepted,
        "binding_matches_current_artifacts": binding_matches,
        "reviewed_at_utc": latest.get("created_at_utc"),
        "reviewer": latest.get("reviewer"),
        "notes": latest.get("notes"),
        "binding_sha256": latest.get("binding", {}).get("binding_sha256"),
        "event_sha256": latest.get("event_sha256"),
        "event_count": len(payload["events"]),
    }


def record_human_review(
    settings: Settings,
    *,
    action: str,
    reviewer: str,
    notes: str = "",
) -> dict:
    if action not in {"accepted", "revoked"}:
        raise SystemExit("Review action must be accepted or revoked.")
    reviewer = reviewer.strip()
    notes = notes.strip()
    if not reviewer:
        raise SystemExit("--reviewer is required and must identify the human reviewer.")
    if len(reviewer) > 200 or len(notes) > 4000:
        raise SystemExit("Reviewer name or review notes exceed the safe ledger limit.")
    if any(ord(character) < 32 and character not in "\n\t" for character in reviewer + notes):
        raise SystemExit("Reviewer name or review notes contain unsupported control characters.")
    review_metadata = f"{reviewer}\n{notes}"
    if re.search(
        r"\b(?:sk-(?:proj-)?|github_pat_|ghp_)[A-Za-z0-9_-]{20,}",
        review_metadata,
    ):
        raise SystemExit("Review metadata appears to contain a credential; refusing to persist it.")
    # Acceptance is not a cosmetic flag: validate the complete analysis first.
    validate_analysis_artifacts(settings, require_dashboard=True)
    binding = current_review_binding(settings)
    path = settings.human_review_ledger_path
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise SystemExit(
                "Existing human-review ledger is unreadable; refusing to overwrite it."
            ) from None
        valid, reason = _validate_review_events(payload)
        if not valid:
            raise SystemExit(f"Existing human-review ledger is invalid ({reason}); refusing to overwrite it.")
    else:
        payload = {"schema_version": REVIEW_SCHEMA_VERSION, "events": [], "head_event_sha256": None}
    previous = payload.get("head_event_sha256")
    event = {
        "sequence": len(payload["events"]) + 1,
        "action": action,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "reviewer": reviewer,
        "notes": notes,
        "binding": binding,
        "previous_event_sha256": previous,
    }
    event["event_sha256"] = sha256_json(event)
    payload["events"].append(event)
    payload["head_event_sha256"] = event["event_sha256"]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)
    invalidate_publication_snapshot(settings)
    return get_human_review_status(settings)


def get_publication_review_status(settings: Settings) -> dict:
    path = settings.publication_review_ledger_path
    if not path.is_file():
        return {
            "status": "not_reviewed",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "invalid",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
            "reason": "unreadable_ledger",
        }
    if not isinstance(payload, dict):
        return {
            "status": "invalid",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
            "reason": "invalid_ledger",
        }
    ledger_valid, reason = _validate_review_events(
        payload,
        schema_version=PUBLICATION_REVIEW_SCHEMA_VERSION,
    )
    if not ledger_valid:
        return {
            "status": "invalid",
            "ledger_valid": False,
            "accepted_for_current_artifacts": False,
            "reason": reason,
        }
    latest = payload["events"][-1]
    evidence = get_human_review_status(settings)
    current = None
    if evidence.get("accepted_for_current_artifacts"):
        try:
            current = build_publication_binding(settings, current_review_binding(settings))
        except SystemExit:
            current = None
    binding_matches = bool(
        current
        and latest.get("binding", {}).get("binding_sha256")
        == current.get("binding_sha256")
    )
    accepted = latest.get("action") == "accepted" and binding_matches
    return {
        "status": "accepted" if accepted else "stale",
        "ledger_valid": True,
        "accepted_for_current_artifacts": accepted,
        "binding_matches_current_artifacts": binding_matches,
        "reviewed_at_utc": latest.get("created_at_utc"),
        "binding_sha256": latest.get("binding", {}).get("binding_sha256"),
        "event_sha256": latest.get("event_sha256"),
        "event_count": len(payload["events"]),
        "binding": latest.get("binding") if accepted else None,
    }


def record_publication_review(
    settings: Settings,
    *,
    reviewer: str,
    notes: str = "",
) -> dict:
    if settings.publication_mode != "public":
        raise SystemExit("Publication acceptance requires PUBLICATION_MODE=public.")
    reviewer = reviewer.strip()
    notes = notes.strip()
    if not reviewer:
        raise SystemExit("--reviewer is required and must identify the human reviewer.")
    if len(reviewer) > 200 or len(notes) > 4000:
        raise SystemExit("Reviewer name or review notes exceed the safe ledger limit.")
    if any(ord(character) < 32 and character not in "\n\t" for character in reviewer + notes):
        raise SystemExit("Reviewer name or review notes contain unsupported control characters.")
    if re.search(
        r"\b(?:sk-(?:proj-)?|github_pat_|ghp_)[A-Za-z0-9_-]{20,}",
        f"{reviewer}\n{notes}",
    ):
        raise SystemExit("Review metadata appears to contain a credential; refusing to persist it.")

    validate_analysis_artifacts(settings, require_dashboard=True)
    evidence = get_human_review_status(settings)
    if not evidence.get("accepted_for_current_artifacts"):
        raise SystemExit(
            "Publication acceptance requires a current accepted evidence review first."
        )
    binding = build_publication_binding(settings, current_review_binding(settings))
    path = settings.publication_review_ledger_path
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise SystemExit(
                "Existing publication-review ledger is unreadable; refusing to overwrite it."
            ) from None
        valid, reason = _validate_review_events(
            payload,
            schema_version=PUBLICATION_REVIEW_SCHEMA_VERSION,
        )
        if not valid:
            raise SystemExit(
                f"Existing publication-review ledger is invalid ({reason}); refusing to overwrite it."
            )
    else:
        payload = {
            "schema_version": PUBLICATION_REVIEW_SCHEMA_VERSION,
            "events": [],
            "head_event_sha256": None,
        }
    event = {
        "sequence": len(payload["events"]) + 1,
        "action": "accepted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "reviewer": reviewer,
        "notes": notes,
        "binding": binding,
        "previous_event_sha256": payload.get("head_event_sha256"),
    }
    event["event_sha256"] = sha256_json(event)
    payload["events"].append(event)
    payload["head_event_sha256"] = event["event_sha256"]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)
    invalidate_publication_snapshot(settings)
    return get_publication_review_status(settings)


def _sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return ""
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return ""
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path, "", ""))


def _sanitized_runtime_settings(
    settings: Settings,
    policy_manifest: list[dict],
    provided_manifest: dict | None,
) -> dict:
    return {
        "schema_version": "sanitized-runtime-settings-v1",
        "app_version": __version__,
        "project_name": settings.project_name,
        "analyst_name": settings.analyst_name,
        "source": {
            "mode": settings.source_mode,
            "channel_id": settings.youtube_channel_id,
            "channel_url": _sanitize_url(settings.youtube_channel_url),
            "date_range": {"start": str(settings.start_date), "end": str(settings.end_date)},
            "max_audit_days": settings.max_audit_days,
            "max_scan_items": settings.max_scan_items,
            "strict_source_channel": settings.strict_source_channel,
            "source_rights_acknowledged": settings.source_rights_acknowledged,
            "subtitle_languages": list(settings.subtitle_languages),
            "require_subtitles_for_audit": settings.require_subtitles_for_audit,
            "collect_thumbnails": settings.collect_thumbnails,
            "provided_sources_manifest": provided_manifest,
        },
        "transcription": {
            "enabled": settings.transcription_fallback,
            "model": settings.openai_transcription_model,
            "language": settings.transcription_language,
            "prompt_configured": bool(settings.transcription_prompt),
            "chunk_seconds": settings.transcription_chunk_seconds,
            "retain_raw_audio": settings.retain_raw_audio,
        },
        "analysis": {
            "mode": settings.audit_mode,
            "claim_model": settings.openai_claim_model,
            "scoring_model": settings.openai_scoring_model,
            "claim_reasoning_effort": settings.openai_claim_reasoning_effort,
            "scoring_reasoning_effort": settings.openai_scoring_reasoning_effort,
            "max_retries": settings.openai_max_retries,
            "concurrency": settings.openai_concurrency,
            "timeout_seconds": settings.openai_timeout_seconds,
            "api_cost_acknowledged": settings.api_cost_acknowledged,
        },
        "policy": {
            "audit_scope_categories": list(settings.audit_scope_categories),
            "price_outcome_only": settings.price_outcome_only,
            "international_market_provider": settings.international_market_provider,
            "report_default_language": settings.report_default_language,
            "policy_configs": policy_manifest,
        },
        "publication": {
            "mode": settings.publication_mode,
            "public_claim_ledger": settings.public_claim_ledger,
        },
        "redactions": [
            "OPENAI_API_KEY",
            "TRANSCRIPTION_PROMPT value",
            "absolute workspace/import/market-data paths",
        ],
    }


def _preserve_operator_inputs(
    settings: Settings,
    components_dir: Path,
    *,
    allow_missing_provided_manifest: bool = False,
) -> tuple[list[dict], dict | None]:
    policy_dir = components_dir / "policy_configs"
    policy_manifest: list[dict] = []
    for role, source in (
        ("category_overrides", settings.category_overrides_file),
        ("asset_map", settings.asset_map_file),
    ):
        if source is None:
            continue
        resolved = source.expanduser().resolve()
        if not resolved.is_file():
            raise SystemExit(f"Cannot finalize; configured {role} file is missing.")
        policy_dir.mkdir(parents=True, exist_ok=True)
        target = policy_dir / f"{role}{resolved.suffix or '.json'}"
        shutil.copy2(resolved, target)
        policy_manifest.append({
            "role": role,
            "file": str(target.relative_to(components_dir)),
            "original_name": resolved.name,
            "sha256": sha256_file(target),
        })
    if policy_manifest:
        write_json_atomic(policy_dir / "manifest.json", {"configs": policy_manifest})

    provided_manifest = None
    if settings.source_mode == "provided":
        # Preserve the importer's normalized, in-range ledger. The operator's
        # original sources.json can contain unrelated records or local paths.
        source = settings.raw_dir / "provided_sources.manifest.json"
        if source.is_file():
            target_dir = components_dir / "provided_sources"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / "manifest.json"
            shutil.copy2(source, target)
            provided_manifest = {
                "file": str(target.relative_to(components_dir)),
                "sha256": sha256_file(target),
            }
        elif not allow_missing_provided_manifest:
            raise SystemExit("Cannot finalize; provided-source manifest is missing.")
    return policy_manifest, provided_manifest


def _preserve_market_evidence(settings: Settings, outcomes: dict, components_dir: Path) -> dict:
    target_dir = components_dir / "market_evidence"
    target_dir.mkdir(parents=True, exist_ok=True)
    references: dict[str, str] = {}
    for item in outcomes.get("series", {}).values():
        if isinstance(item, dict) and item.get("source_file") and item.get("source_sha256"):
            references[str(item["source_file"])] = str(item["source_sha256"])
    for claim in outcomes.get("claims", []):
        if not isinstance(claim, dict):
            continue
        for item in claim.get("assets", []):
            if (
                isinstance(item, dict)
                and item.get("status") == "available"
                and item.get("source_file")
                and item.get("source_sha256")
            ):
                source_file = str(item["source_file"])
                source_hash = str(item["source_sha256"])
                existing = references.get(source_file)
                if existing is not None and existing != source_hash:
                    raise SystemExit("Cannot finalize; one market source path has conflicting hashes.")
                references[source_file] = source_hash

    files = []
    omitted_synthetic = []
    synthetic_private_demo = bool(outcomes.get("synthetic_demo")) and settings.publication_mode == "private"
    for relative_path, expected_hash in sorted(references.items()):
        source = _workspace_file(settings, relative_path, label="market source_file")
        if not source.is_file() or sha256_file(source) != expected_hash:
            if synthetic_private_demo:
                omitted_synthetic.append({
                    "workspace_relative_path": relative_path,
                    "recorded_sha256": expected_hash,
                    "reason": "synthetic demo reference; no real market file exists",
                })
                continue
            raise SystemExit(f"Cannot finalize; market source hash failed for {Path(relative_path).name}.")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.name) or "market-data.bin"
        copied_name = f"{expected_hash[:16]}__{safe_name}"
        target = target_dir / copied_name
        shutil.copy2(source, target)
        if sha256_file(target) != expected_hash:
            raise SystemExit(f"Cannot finalize; copied market source hash failed for {source.name}.")
        files.append({
            "workspace_relative_path": relative_path,
            "copied_file": copied_name,
            "sha256": expected_hash,
            "size_bytes": target.stat().st_size,
        })
    payload = {
        "schema_version": "portable-market-evidence-v1",
        "files": files,
        "omitted_synthetic_references": omitted_synthetic,
    }
    write_json_atomic(target_dir / "manifest.json", payload)
    return payload


def _bundled_review_is_valid(final_dir: Path, final_manifest: dict) -> bool:
    components = final_dir / "components"
    ledger_path = components / "human_review" / "human_review.json"
    public_mode = final_manifest.get("publication", {}).get("mode") == "public"
    if not ledger_path.is_file():
        return not public_mode
    try:
        ledger = _read_json(ledger_path)
        valid, _reason = _validate_review_events(ledger)
        if not valid:
            return False
        if not public_mode:
            return True
        outcomes = _read_json(components / "outcomes.json")
        scoring = _read_json(components / "scores_summary.json")
        manifest = _read_json(components / "manifest.json")
        binding = {
            "publication_mode": final_manifest.get("publication", {}).get("mode"),
            "collection_id": manifest.get("collection_id"),
            "collection_manifest_sha256": sha256_file(components / "manifest.json"),
            "claims_summary_sha256": sha256_file(components / "claims_summary.json"),
            "claims_ledger_sha256": sha256_file(components / "claims.jsonl"),
            "outcome_snapshot_sha256": outcomes.get("outcome_snapshot_sha256"),
            "outcome_artifact_sha256": sha256_file(components / "outcomes.json"),
            "scoring_run_sha256": sha256_file(components / "scores_summary.json"),
            "scoring_ledger_sha256": sha256_file(components / "scores.jsonl"),
            "scoring_run_id": scoring.get("scoring_run_id"),
        }
        binding["binding_sha256"] = sha256_json(binding)
        latest = ledger["events"][-1]
        binding_matches = latest.get("binding", {}).get("binding_sha256") == binding["binding_sha256"]
        manifest_matches = (
            final_manifest.get("publication", {}).get("human_review_binding_sha256")
            == binding["binding_sha256"]
        )
        evidence_review_valid = (
            binding_matches and manifest_matches and latest.get("action") == "accepted"
        )
        if not evidence_review_valid:
            return False

        publication_ledger = _read_json(components / "human_review" / "publication_review.json")
        publication_valid, _publication_reason = _validate_review_events(
            publication_ledger,
            schema_version=PUBLICATION_REVIEW_SCHEMA_VERSION,
        )
        if not publication_valid:
            return False
        publication_event = publication_ledger["events"][-1]
        snapshot = _read_json(components / "reports" / PUBLICATION_MANIFEST_NAME)
        recorded_snapshot_hash = snapshot.get("snapshot_sha256")
        snapshot_core = dict(snapshot)
        snapshot_core.pop("snapshot_sha256", None)
        publication_binding = snapshot.get("publication_binding")
        if not isinstance(publication_binding, dict):
            return False
        publication_binding_hash = publication_binding.get("binding_sha256")
        publication_binding_core = dict(publication_binding)
        publication_binding_core.pop("binding_sha256", None)
        return bool(
            publication_event.get("action") == "accepted"
            and publication_event.get("event_sha256")
            == snapshot.get("publication_review", {}).get("event_sha256")
            and publication_event.get("binding", {}).get("binding_sha256")
            == publication_binding_hash
            and snapshot.get("publication_review", {}).get("binding_sha256")
            == publication_binding_hash
            and sha256_json(publication_binding_core) == publication_binding_hash
            and snapshot.get("evidence_review_binding", {}).get("binding_sha256")
            == binding["binding_sha256"]
            and sha256_json(snapshot_core) == recorded_snapshot_hash
            and final_manifest.get("publication", {}).get(
                "publication_review_binding_sha256"
            )
            == publication_binding_hash
            and final_manifest.get("publication", {}).get("publication_snapshot_sha256")
            == recorded_snapshot_hash
        )
    except (AttributeError, OSError, KeyError, TypeError, SystemExit):
        return False


def verify_final_audit(settings: Settings) -> dict:
    final_dir = settings.workspace_dir / "final_audit"
    inventory_path = final_dir / "file_hashes.csv"
    hashes_path = final_dir / "pack_hashes.json"
    manifest_path = final_dir / "final_manifest.json"
    summary_path = settings.workspace_dir / "final_audit_summary.json"
    missing = [
        str(path)
        for path in (inventory_path, hashes_path, manifest_path, summary_path)
        if not path.is_file()
    ]
    if missing:
        return {"status": "not_available", "verified": False, "missing_required_files": missing}

    try:
        with inventory_path.open(encoding="utf-8-sig", newline="") as handle:
            inventory = list(csv.DictReader(handle))
        relative_paths = [row["relative_path"] for row in inventory]
        invalid_inventory_paths = [
            value for value in relative_paths
            if Path(value).is_absolute() or ".." in Path(value).parts
        ]
        duplicate_inventory_paths = [
            value for value, count in Counter(relative_paths).items() if count > 1
        ]
        failed_files = []
        for row in inventory:
            path = final_dir / row["relative_path"]
            if (
                not path.is_file()
                or path.stat().st_size != int(row["size_bytes"])
                or sha256_file(path) != row["sha256"]
            ):
                failed_files.append(row["relative_path"])
        expected_inventory = {
            str(path.relative_to(final_dir))
            for path in final_dir.rglob("*")
            if path.is_file() and path not in {inventory_path, hashes_path}
        }
        untracked_files = sorted(expected_inventory - set(relative_paths))
        nonexistent_inventory_files = sorted(set(relative_paths) - expected_inventory)
        pack_hashes = _read_json(hashes_path)
        collection_zip = final_dir / "components" / str(pack_hashes.get("collection_zip_name", ""))
        failed_pack_hashes = []
        for key, path in (
            ("final_manifest_sha256", manifest_path),
            ("file_hashes_csv_sha256", inventory_path),
            ("collection_zip_sha256", collection_zip),
        ):
            if not path.is_file() or sha256_file(path) != pack_hashes.get(key):
                failed_pack_hashes.append(key)
        final_manifest = _read_json(manifest_path)
        summary = _read_json(summary_path)
    except (KeyError, ValueError, TypeError, SystemExit) as exc:
        return {"status": "failed", "verified": False, "reason": str(exc)}

    zip_name = Path(str(summary.get("zip_path", ""))).name
    zip_path = settings.workspace_dir / zip_name
    zip_hash_matches = zip_path.is_file() and sha256_file(zip_path) == summary.get("zip_sha256")
    bad_member = None
    zip_inventory_matches = False
    if zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path) as archive:
                bad_member = archive.testzip()
                expected_members = {
                    str(Path("final_audit") / path.relative_to(final_dir))
                    for path in final_dir.rglob("*") if path.is_file()
                }
                zip_inventory_matches = set(archive.namelist()) == expected_members
        except zipfile.BadZipFile:
            bad_member = "<invalid-zip>"
    required_component_files = [
        final_dir / "components" / "runtime_settings.public.json",
        final_dir / "components" / "market_evidence" / "manifest.json",
        final_dir / "components" / "analysis" / "claims" / "claims.jsonl",
        final_dir / "components" / "analysis" / "outcomes" / "claim_outcomes.json",
        final_dir / "components" / "analysis" / "scores" / "scores.jsonl",
    ]
    required_components_present = all(path.is_file() for path in required_component_files)
    copied_market_hashes_valid = False
    market_manifest_path = final_dir / "components" / "market_evidence" / "manifest.json"
    try:
        market_manifest = _read_json(market_manifest_path)
        copied_market_hashes_valid = all(
            isinstance(row, dict)
            and isinstance(row.get("copied_file"), str)
            and Path(row["copied_file"]).name == row["copied_file"]
            and isinstance(row.get("workspace_relative_path"), str)
            and not Path(row["workspace_relative_path"]).is_absolute()
            and ".." not in Path(row["workspace_relative_path"]).parts
            and (market_manifest_path.parent / row["copied_file"]).is_file()
            and sha256_file(market_manifest_path.parent / row["copied_file"]) == row.get("sha256")
            for row in market_manifest.get("files", [])
        )
    except (SystemExit, TypeError):
        copied_market_hashes_valid = False
    manifest_matches_summary = (
        final_manifest.get("collection_id") == summary.get("collection_id")
        and final_manifest.get("app_version") == __version__
        and final_manifest.get("schema_version") == FINAL_BUNDLE_SCHEMA_VERSION
    )
    bundled_review_valid = _bundled_review_is_valid(final_dir, final_manifest)
    verified = not any((
        failed_files,
        failed_pack_hashes,
        invalid_inventory_paths,
        duplicate_inventory_paths,
        untracked_files,
        nonexistent_inventory_files,
        not zip_hash_matches,
        bad_member,
        not zip_inventory_matches,
        not required_components_present,
        not copied_market_hashes_valid,
        not manifest_matches_summary,
        not bundled_review_valid,
    ))
    return {
        "status": "verified" if verified else "failed",
        "verified": verified,
        "inventory_file_count": len(inventory),
        "failed_file_hash_count": len(failed_files),
        "failed_files": failed_files[:20],
        "failed_pack_hashes": failed_pack_hashes,
        "invalid_inventory_paths": invalid_inventory_paths[:20],
        "duplicate_inventory_paths": duplicate_inventory_paths[:20],
        "untracked_files": untracked_files[:20],
        "nonexistent_inventory_files": nonexistent_inventory_files[:20],
        "zip_path": str(zip_path),
        "zip_sha256_matches": zip_hash_matches,
        "zip_inventory_matches": zip_inventory_matches,
        "zip_first_bad_member": bad_member,
        "required_components_present": required_components_present,
        "copied_market_hashes_valid": copied_market_hashes_valid,
        "manifest_matches_summary": manifest_matches_summary,
        "bundled_review_valid": bundled_review_valid,
    }


def finalize_audit(settings: Settings) -> Path:
    review = get_human_review_status(settings)
    publication_review = get_publication_review_status(settings)
    if settings.publication_mode == "public" and not review.get("accepted_for_current_artifacts"):
        raise SystemExit(
            "Cannot finalize a public audit until a human accepts the current artifact binding. "
            "Run `python -m audit_lab.cli review accept --reviewer NAME --notes TEXT`, "
            "then regenerate the report."
        )
    if (
        settings.publication_mode == "public"
        and not publication_review.get("accepted_for_current_artifacts")
    ):
        raise SystemExit(
            "Cannot finalize a public audit until a human accepts the exact dashboard, PDF, "
            "and optional claim ledger. Inspect the finished outputs, then run "
            "`python -m audit_lab.cli review publication-accept --reviewer NAME --notes TEXT`."
        )

    validated = validate_analysis_artifacts(settings, require_dashboard=True)
    manifest = validated["manifest"]
    collection_summary = validated["collection_summary"]
    claims_summary = validated["claims_summary"]
    outcomes_summary = validated["outcomes"]
    scores_summary = validated["scores_summary"]
    collection_id = validated["collection_id"]

    collection_zip = Path(str(collection_summary.get("zip_path", "")))
    if not collection_zip.is_file():
        candidate = settings.workspace_dir / collection_zip.name
        collection_zip = candidate if candidate.is_file() else collection_zip
    if not collection_zip.is_file() or sha256_file(collection_zip) != collection_summary.get("zip_sha256"):
        raise SystemExit("Cannot finalize; collection ZIP is missing or does not match its recorded hash.")

    final_dir = settings.workspace_dir / "final_audit"
    if final_dir.exists():
        shutil.rmtree(final_dir)
    final_dir.mkdir(parents=True)
    components_dir = final_dir / "components"
    components_dir.mkdir()

    shutil.copy2(collection_zip, components_dir / collection_zip.name)
    for name, path in validated["paths"].items():
        target = components_dir / f"{name}{path.suffix}"
        shutil.copy2(path, target)
    analysis_dir = components_dir / "analysis"
    for name, source in (
        ("claims", settings.claims_dir),
        ("outcomes", settings.outcomes_dir),
        ("scores", settings.scores_dir),
    ):
        shutil.copytree(source, analysis_dir / name)
    if settings.logs_dir.exists():
        shutil.copytree(settings.logs_dir, components_dir / "audit_logs")
    if settings.reports_dir.exists():
        shutil.copytree(
            settings.reports_dir,
            components_dir / "reports",
            ignore=shutil.ignore_patterns(PUBLICATION_MANIFEST_NAME),
        )
    if settings.human_review_ledger_path.is_file():
        review_dir = components_dir / "human_review"
        review_dir.mkdir()
        shutil.copy2(settings.human_review_ledger_path, review_dir / "human_review.json")
        if settings.publication_review_ledger_path.is_file():
            shutil.copy2(
                settings.publication_review_ledger_path,
                review_dir / "publication_review.json",
            )

    publication_snapshot = None
    if settings.publication_mode == "public":
        evidence_binding = current_review_binding(settings)
        publication_snapshot = build_publication_snapshot(
            reports_dir=components_dir / "reports",
            claims_path=analysis_dir / "claims" / "claims.jsonl",
            scores_path=analysis_dir / "scores" / "scores.jsonl",
            outcomes_path=analysis_dir / "outcomes" / "claim_outcomes.json",
            evidence_review_binding=evidence_binding,
            publication_binding=publication_review["binding"],
            publication_event_sha256=str(publication_review.get("event_sha256") or ""),
            publication_reviewed_at_utc=publication_review.get("reviewed_at_utc"),
        )
        write_json_atomic(
            components_dir / "reports" / PUBLICATION_MANIFEST_NAME,
            publication_snapshot,
        )

    policy_manifest, provided_manifest = _preserve_operator_inputs(
        settings,
        components_dir,
        allow_missing_provided_manifest=validated["synthetic_private_demo"],
    )
    portable_market_evidence = _preserve_market_evidence(settings, outcomes_summary, components_dir)
    write_json_atomic(
        components_dir / "runtime_settings.public.json",
        _sanitized_runtime_settings(settings, policy_manifest, provided_manifest),
    )

    project_root = Path(__file__).resolve().parents[2]
    methodology_dir = final_dir / "methodology"
    methodology_dir.mkdir()
    for path in (
        project_root / "README.md",
        project_root / "docs" / "en" / "methodology.md",
        project_root / "docs" / "fa" / "methodology.md",
        project_root / "docs" / "en" / "fairness-and-publication.md",
        project_root / "docs" / "fa" / "fairness-and-publication.md",
        project_root / "docs" / "en" / "privacy.md",
        project_root / "docs" / "fa" / "privacy.md",
        project_root / "audit_lab" / "prompts" / "claim_extraction_system.md",
        project_root / "audit_lab" / "prompts" / "scoring_system.md",
        project_root / "audit_lab" / "schemas" / "claim_extraction.schema.json",
    ):
        if path.is_file():
            if path.name in {"methodology.md", "fairness-and-publication.md", "privacy.md"}:
                target_name = f"{path.parent.name}__{path.name}"
            else:
                target_name = path.name
            shutil.copy2(path, methodology_dir / target_name)

    reproduction_dir = final_dir / "reproduction"
    reproduction_dir.mkdir()
    for path in (
        project_root / "Dockerfile",
        project_root / "docker-compose.yml",
        project_root / "requirements.txt",
        project_root / "requirements.lock",
        project_root / "pyproject.toml",
        project_root / "Makefile",
        project_root / ".env.example",
        project_root / "LICENSE",
        project_root / "NOTICE",
    ):
        if path.is_file():
            shutil.copy2(path, reproduction_dir / path.name)
    reproduction_scripts_dir = reproduction_dir / "scripts"
    reproduction_scripts_dir.mkdir()
    report_script = project_root / "scripts" / "generate_audit_report.py"
    if report_script.is_file():
        shutil.copy2(report_script, reproduction_scripts_dir / report_script.name)
    shutil.copytree(
        project_root / "audit_lab",
        reproduction_dir / "audit_lab",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    final_manifest = {
        "schema_version": FINAL_BUNDLE_SCHEMA_VERSION,
        "app_version": __version__,
        "audit_name": settings.project_name,
        "collection_id": collection_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "date_range": manifest.get("date_range"),
        "channel": {
            "id": manifest.get("channel", {}).get("id"),
            "url": _sanitize_url(str(manifest.get("channel", {}).get("url") or "")),
            "analyst_name": manifest.get("channel", {}).get("analyst_name"),
        },
        "publication": {
            "mode": settings.publication_mode,
            "human_review_required": settings.publication_mode == "public",
            "human_review_accepted": bool(review.get("accepted_for_current_artifacts")),
            "human_review_binding_sha256": review.get("binding_sha256"),
            "publication_review_required": settings.publication_mode == "public",
            "publication_review_accepted": bool(
                publication_review.get("accepted_for_current_artifacts")
            ),
            "publication_review_binding_sha256": publication_review.get("binding_sha256"),
            "publication_snapshot_sha256": (
                publication_snapshot.get("snapshot_sha256") if publication_snapshot else None
            ),
        },
        "audit_scope": {
            "categories": list(settings.audit_scope_categories),
            "price_outcome_only": settings.price_outcome_only,
            "category_policy": (
                "Only configured scope categories enter scoring; other collected categories "
                "remain in the source ledger."
            ),
        },
        "collection_verified": True,
        "preflight": {
            "claim_ledger_rows": validated["claim_count"],
            "score_ledger_rows": validated["score_count"],
            "market_source_hashes_checked": validated["market_source_hash_count"],
            "per_video_artifacts_reconciled": True,
            "aggregates_recomputed": True,
        },
        "videos_found": manifest.get("summary", {}).get("total_videos_found"),
        "videos_included": manifest.get("summary", {}).get("videos_included"),
        "claims": {
            "run_id": claims_summary.get("extraction_run_id"),
            "schema_version": claims_summary.get("schema_version"),
            "evidence_policy": claims_summary.get("evidence_policy"),
            "model": claims_summary.get("model"),
            "prompt_sha256": claims_summary.get("prompt_sha256"),
            "usage": claims_summary.get("usage_all_artifacts"),
            "total": claims_summary.get("total_claims"),
            "scoreable": claims_summary.get("scoreable_claims"),
            "conditional": claims_summary.get("conditional_claims"),
            "not_scoreable": claims_summary.get("not_scoreable_claims"),
        },
        "outcomes": {
            "provider": outcomes_summary.get("provider"),
            "created_at_utc": outcomes_summary.get("created_at_utc"),
            "snapshot_sha256": outcomes_summary.get("outcome_snapshot_sha256"),
            "market_evidence_snapshot_sha256": outcomes_summary.get("market_evidence_snapshot_sha256"),
        },
        "scoring": {
            "run_id": scores_summary.get("scoring_run_id"),
            "schema_version": scores_summary.get("schema_version"),
            "scoring_policy": scores_summary.get("scoring_policy"),
            "artifact_fingerprints_sha256": validated["scoring_fingerprints_sha256"],
            "model": scores_summary.get("model"),
            "prompt_sha256": scores_summary.get("prompt_sha256"),
            "usage": scores_summary.get("usage_all_artifacts"),
            "final_score": scores_summary.get("final_score"),
            "counted_claims": scores_summary.get("counted_claims"),
            "total_claims": scores_summary.get("total_claims"),
            "results": scores_summary.get("results"),
            "category_breakdown": scores_summary.get("category_breakdown"),
        },
        "preserved_inputs": {
            "runtime_settings": "components/runtime_settings.public.json",
            "policy_configs": policy_manifest,
            "provided_sources_manifest": provided_manifest,
            "market_evidence_manifest": "components/market_evidence/manifest.json",
            "market_evidence_file_count": len(portable_market_evidence["files"]),
        },
        "limitations": [
            "Incomplete outcome windows are excluded from the score.",
            (
                "Every asset named in a multi-asset claim must have a complete usable outcome "
                "window before the claim can be scored."
            ),
            (
                "Categories outside AUDIT_SCOPE_CATEGORIES are retained in the collection ledger "
                "but excluded from scoring."
            ),
            (
                "Context inputs such as liquidation maps, ETF flows, and macro explanations "
                "are not independently scored."
            ),
            "Market-data providers and venues may differ at borderline levels.",
            (
                "AI assists extraction and rule application; human review does not convert "
                "output into ground truth."
            ),
            (
                "SHA-256 inventories verify a captured bundle; they are not an independent "
                "timestamp or signature."
            ),
        ],
    }
    write_json_atomic(final_dir / "final_manifest.json", final_manifest)

    inventory = []
    for path in sorted(final_dir.rglob("*")):
        if path.is_file():
            inventory.append({
                "relative_path": str(path.relative_to(final_dir)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    inventory_path = final_dir / "file_hashes.csv"
    with inventory_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relative_path", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows(inventory)
    write_json_atomic(final_dir / "pack_hashes.json", {
        "final_manifest_sha256": sha256_file(final_dir / "final_manifest.json"),
        "file_hashes_csv_sha256": sha256_file(inventory_path),
        "collection_zip_name": collection_zip.name,
        "collection_zip_sha256": sha256_file(components_dir / collection_zip.name),
    })

    zip_path = settings.workspace_dir / f"complete_audit_{collection_id}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(final_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(settings.workspace_dir))
    with zipfile.ZipFile(zip_path) as archive:
        bad_member = archive.testzip()
    if bad_member:
        raise SystemExit(f"Final ZIP validation failed at {bad_member}")
    write_json_atomic(settings.workspace_dir / "final_audit_summary.json", {
        "schema_version": FINAL_BUNDLE_SCHEMA_VERSION,
        "app_version": __version__,
        "collection_id": collection_id,
        "zip_path": zip_path.name,
        "zip_sha256": sha256_file(zip_path),
        "zip_valid": True,
        "file_count": len(inventory) + 2,
        "final_score": scores_summary.get("final_score"),
        "publication_mode": settings.publication_mode,
        "human_review_binding_sha256": review.get("binding_sha256"),
        "publication_review_binding_sha256": publication_review.get("binding_sha256"),
        "publication_snapshot_sha256": (
            publication_snapshot.get("snapshot_sha256") if publication_snapshot else None
        ),
    })
    verification = verify_final_audit(settings)
    if not verification.get("verified"):
        raise SystemExit("Final audit bundle was created but failed post-build verification.")
    if publication_snapshot is not None:
        write_json_atomic(
            settings.reports_dir / PUBLICATION_MANIFEST_NAME,
            publication_snapshot,
        )
    return zip_path
