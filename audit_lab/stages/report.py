from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from audit_lab.settings import Settings
from audit_lab.publication import invalidate_publication_snapshot
from audit_lab.stages.finalize import get_human_review_status
from audit_lab.stages.score_claims import outcome_supports_window, required_evaluation_window
from audit_lab.stages.verify import verify_audit_pack


RESULT_LABELS = {
    "correct": "Fully aligned",
    "partially_correct": "Partly aligned",
    "incorrect": "Missed",
    "not_triggered": "Scenario did not activate",
    "insufficient_data": "Limited evidence",
    "not_scoreable": "Context, not a price call",
}

CATEGORY_LABELS = {
    "global_markets": "International markets",
    "crypto": "Crypto",
    "local_markets": "Local markets",
}


def _percent(value: int | float, total: int | float) -> float:
    return round(value / total * 100, 1) if total else 0.0


def _score_presentation(scores: dict | None) -> dict | None:
    if not scores:
        return None
    total = int(scores.get("total_claims", 0))
    counted = int(scores.get("counted_claims", 0))
    results = scores.get("results", {})
    score = scores.get("final_score")
    not_triggered = int(results.get("not_triggered", 0))
    insufficient = int(results.get("insufficient_data", 0))
    outside_scope = int(results.get("not_scoreable", 0))
    data_supported = max(total - insufficient - outside_scope, 0)
    resolved = counted + not_triggered
    score_bearing_percent = _percent(counted, total)
    evidence_coverage_percent = _percent(data_supported, total)
    resolution_percent = _percent(resolved, total)
    activation_percent = _percent(counted, resolved)
    correct_count = int(results.get("correct", 0))
    partial_count = int(results.get("partially_correct", 0))
    incorrect_count = int(results.get("incorrect", 0))
    at_least_partial_count = correct_count + partial_count
    at_least_partial_percent = _percent(at_least_partial_count, counted)

    counted_results = []
    for key in ["correct", "partially_correct", "incorrect"]:
        count = int(results.get(key, 0))
        counted_results.append({
            "key": key,
            "label": RESULT_LABELS[key],
            "count": count,
            "percent": _percent(count, counted),
        })
    excluded_results = []
    for key in ["not_triggered", "insufficient_data", "not_scoreable"]:
        count = int(results.get(key, 0))
        excluded_results.append({
            "key": key,
            "label": RESULT_LABELS[key],
            "count": count,
            "percent_of_all": _percent(count, total),
        })

    categories = []
    breakdown = scores.get("category_breakdown", {})
    category_order = sorted(breakdown)
    for key in category_order:
        category = breakdown.get(key)
        if not category:
            continue
        category_total = int(category.get("total_claims", 0))
        category_counted = int(category.get("counted_claims", 0))
        category_results = category.get("results", {})
        category_correct = int(category_results.get("correct", 0))
        category_partial = int(category_results.get("partially_correct", 0))
        category_incorrect = int(category_results.get("incorrect", 0))
        category_at_least_partial = category_correct + category_partial
        category_not_triggered = int(category_results.get("not_triggered", 0))
        category_insufficient = int(category_results.get("insufficient_data", 0))
        category_outside = int(category_results.get("not_scoreable", 0))
        category_supported = max(category_total - category_insufficient - category_outside, 0)
        categories.append({
            "key": key,
            "label": CATEGORY_LABELS.get(key, key.replace("_", " ").title()),
            "total_claims": category_total,
            "counted_claims": category_counted,
            "evidence_coverage_percent": _percent(category_supported, category_total),
            "score_bearing_percent": _percent(category_counted, category_total),
            "resolved_claims": category_counted + category_not_triggered,
            "score": category.get("score"),
            "correct": category_correct,
            "partial": category_partial,
            "incorrect": category_incorrect,
            "at_least_partial_count": category_at_least_partial,
            "at_least_partial_percent": _percent(category_at_least_partial, category_counted),
            "not_triggered": category_not_triggered,
            "insufficient": category_insufficient,
            "correct_percent": _percent(category_results.get("correct", 0), category_counted),
            "partial_percent": _percent(category_results.get("partially_correct", 0), category_counted),
            "incorrect_percent": _percent(category_results.get("incorrect", 0), category_counted),
        })

    if score is None or counted < 30:
        conclusion = "Not enough activated calls"
        headline = "The audit is not mature enough for a verdict."
        detail = "Too few price-testable calls reached a scoring decision. The unresolved record remains visible."
        tone = "limited"
    elif evidence_coverage_percent < 50:
        conclusion = "Provisional mixed record"
        headline = "The result is mixed, with an important evidence limit."
        detail = (
            f"The activated, score-bearing calls landed at {score:.2f}/100, while only "
            f"{evidence_coverage_percent:.1f}% of scoped claims had usable price evidence."
        )
        tone = "limited"
    elif score >= 75:
        conclusion = "Strong measured record"
        headline = "The activated, verifiable claims show strong measured alignment."
        detail = f"{at_least_partial_percent:.1f}% of activated, verifiable calls were fully or partly aligned with the price action that followed."
        tone = "positive"
    elif score >= 55:
        conclusion = "Useful daily analysis"
        headline = "The activated claims often aligned with later direction or key levels."
        detail = f"{at_least_partial_percent:.1f}% of activated, verifiable calls were fully or partly aligned. The record is useful, while still leaving room for caution."
        tone = "positive"
    elif score >= 45:
        conclusion = "A useful daily framework"
        headline = "The measured record is mixed, with meaningful partial alignment."
        detail = f"{at_least_partial_percent:.1f}% of activated, verifiable calls were fully or partly aligned. This is a scenario-outcome measure, not a trading win rate or profitability proof."
        tone = "mixed"
    else:
        conclusion = "Useful context, with caution"
        headline = "The daily framework can be useful, but the calls need careful risk management."
        detail = f"{at_least_partial_percent:.1f}% of activated calls were fully or partly aligned; misses remain significant and should stay visible."
        tone = "mixed"

    weighted_points = int(results.get("correct", 0)) + 0.5 * int(results.get("partially_correct", 0))
    return {
        "score": score,
        "total_claims": total,
        "counted_claims": counted,
        "not_counted_claims": max(total - counted, 0),
        "data_supported_claims": data_supported,
        "resolved_claims": resolved,
        "not_triggered_claims": not_triggered,
        "score_bearing_percent": score_bearing_percent,
        "coverage_percent": score_bearing_percent,
        "evidence_coverage_percent": evidence_coverage_percent,
        "resolution_percent": resolution_percent,
        "activation_percent": activation_percent,
        "at_least_partial_count": at_least_partial_count,
        "at_least_partial_percent": at_least_partial_percent,
        "correct_count": correct_count,
        "partial_count": partial_count,
        "incorrect_count": incorrect_count,
        "weighted_points": weighted_points,
        "counted_results": counted_results,
        "excluded_results": excluded_results,
        "categories": categories,
        "conclusion": conclusion,
        "headline": headline,
        "conclusion_detail": detail,
        "conclusion_tone": tone,
    }


def _outcome_presentation(
    outcomes: dict | None,
    claims_by_id: dict[str, dict] | None = None,
) -> dict | None:
    if not outcomes:
        return None
    complete_claims = 0
    for outcome in outcomes.get("claims", []):
        claim = (claims_by_id or {}).get(outcome.get("claim_id"), {})
        evaluation_window = required_evaluation_window(claim) if claim else None
        if evaluation_window and outcome_supports_window(outcome, evaluation_window):
            complete_claims += 1
    series = outcomes.get("series", {})
    providers = []
    for item in outcomes.get("providers", []):
        provider_series = [value for value in series.values() if value.get("provider") == item["name"]]
        providers.append({
            **item,
            "series_count": len(provider_series),
            "row_count": sum(int(value.get("row_count", 0)) for value in provider_series),
            "raw_file_count": sum(int(value.get("raw_file_count", 0)) for value in provider_series),
            "checksums_verified": sum(int(value.get("upstream_checksums_verified", 0)) for value in provider_series),
        })
    return {
        "complete_claims": complete_claims,
        "available_series": sum(1 for item in series.values() if item.get("status") == "available"),
        "provider": outcomes.get("provider"),
        "providers": providers,
        "snapshot_sha256": outcomes.get("outcome_snapshot_sha256"),
        "market_evidence_snapshot_sha256": outcomes.get("market_evidence_snapshot_sha256"),
    }


def load_manifest(settings: Settings) -> dict | None:
    path = settings.pack_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _scenario_presentation(claim_rows: list[dict], scope_categories: set[str]) -> dict:
    rows = [row for row in claim_rows if row.get("category") in scope_categories]
    by_video: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_video[row["video_id"]].append(row)

    total_claims = len(rows)
    total_videos = len(by_video)
    conditional_claims = sum(row.get("scoreability") == "conditional_scoreable" for row in rows)
    explicit_condition_claims = sum(bool((row.get("condition") or "").strip()) for row in rows)
    level_claims = sum(bool(row.get("levels")) for row in rows)
    multi_level_claims = sum(len(row.get("levels") or []) >= 2 for row in rows)
    invalidation_claims = sum(bool((row.get("invalidation_condition") or "").strip()) for row in rows)
    scenario_claims = sum(row.get("claim_type") == "scenario" for row in rows)
    both_directions_videos = sum(
        {"bullish", "bearish"} <= {row.get("direction") for row in video_rows}
        for video_rows in by_video.values()
    )
    invalidation_videos = sum(
        any(bool((row.get("invalidation_condition") or "").strip()) for row in video_rows)
        for video_rows in by_video.values()
    )
    ten_plus_claim_videos = sum(len(video_rows) >= 10 for video_rows in by_video.values())

    return {
        "total_claims": total_claims,
        "total_videos": total_videos,
        "average_claims_per_video": round(total_claims / total_videos, 1) if total_videos else 0.0,
        "conditional_claims": conditional_claims,
        "conditional_claim_percent": _percent(conditional_claims, total_claims),
        "explicit_condition_claims": explicit_condition_claims,
        "explicit_condition_percent": _percent(explicit_condition_claims, total_claims),
        "level_claims": level_claims,
        "level_claim_percent": _percent(level_claims, total_claims),
        "multi_level_claims": multi_level_claims,
        "multi_level_claim_percent": _percent(multi_level_claims, total_claims),
        "invalidation_claims": invalidation_claims,
        "invalidation_claim_percent": _percent(invalidation_claims, total_claims),
        "scenario_claims": scenario_claims,
        "scenario_claim_percent": _percent(scenario_claims, total_claims),
        "both_directions_videos": both_directions_videos,
        "both_directions_video_percent": _percent(both_directions_videos, total_videos),
        "invalidation_videos": invalidation_videos,
        "invalidation_video_percent": _percent(invalidation_videos, total_videos),
        "ten_plus_claim_videos": ten_plus_claim_videos,
        "ten_plus_claim_video_percent": _percent(ten_plus_claim_videos, total_videos),
    }


def _format_evidence_numbers(text: str | None) -> str | None:
    if not text:
        return text

    def replace(match: re.Match[str]) -> str:
        value = float(match.group(1))
        sign = "+" if match.group(1).startswith("+") else ""
        return f"{sign}{value:,.2f}"

    return re.sub(r"(?<![\w.])([+-]?\d+\.\d{3,})(?![\w.])", replace, text)


def _result_examples(settings: Settings, videos: list[dict], limit_per_result: int = 2) -> list[dict]:
    claims = {row["claim_id"]: row for row in _read_jsonl(settings.claims_dir / "claims.jsonl")}
    scores = _read_jsonl(settings.scores_dir / "scores.jsonl")
    video_by_id = {video["video_id"]: video for video in videos}
    examples = []
    for result in ["correct", "partially_correct", "incorrect"]:
        candidates = [
            score for score in scores
            if score.get("result") == result and score.get("counts_in_final_score")
        ]
        candidates.sort(key=lambda item: (-float(item.get("scoring_confidence", 0)), item["claim_id"]))
        used_categories: set[str] = set()
        chosen = []
        for score in candidates:
            category = score.get("category")
            if category not in used_categories or len(chosen) + len(used_categories) >= limit_per_result:
                chosen.append(score)
                used_categories.add(category)
            if len(chosen) == limit_per_result:
                break
        for score in chosen:
            claim = claims.get(score["claim_id"], {})
            video = video_by_id.get(score.get("video_id"), {})
            examples.append({
                "claim_id": score["claim_id"],
                "result": result,
                "result_label": RESULT_LABELS[result],
                "score": score.get("score"),
                "scoring_confidence": score.get("scoring_confidence"),
                "claim_text": claim.get("claim_text"),
                "source_excerpt": claim.get("source_excerpt"),
                "evidence_summary": score.get("evidence_summary"),
                "evidence_summary_display": _format_evidence_numbers(score.get("evidence_summary")),
                "reasoning": score.get("reasoning"),
                "video_title": video.get("title"),
                "video_url": video.get("webpage_url"),
                "upload_date": video.get("upload_date"),
                "category": video.get("category"),
                "category_label": CATEGORY_LABELS.get(video.get("category"), video.get("category")),
            })
    return examples


def _video_highlights(settings: Settings, videos: list[dict]) -> dict:
    scores = _read_jsonl(settings.scores_dir / "scores.jsonl")
    by_video: dict[str, list[dict]] = defaultdict(list)
    for score in scores:
        by_video[score["video_id"]].append(score)
    video_by_id = {video["video_id"]: video for video in videos}
    rows = []
    for video_id, items in by_video.items():
        counted = [item for item in items if item.get("counts_in_final_score")]
        if len(counted) < 3:
            continue
        points = sum(float(item.get("score", 0)) for item in counted)
        video = video_by_id.get(video_id, {})
        rows.append({
            "video_id": video_id,
            "title": video.get("title"),
            "url": video.get("webpage_url"),
            "date": video.get("upload_date"),
            "category": CATEGORY_LABELS.get(video.get("category"), video.get("category")),
            "score": round(points / len(counted) * 100, 1),
            "counted": len(counted),
            "correct": sum(item.get("result") == "correct" for item in counted),
            "partial": sum(item.get("result") == "partially_correct" for item in counted),
            "incorrect": sum(item.get("result") == "incorrect" for item in counted),
        })
    return {
        "strongest": sorted(rows, key=lambda row: (-row["score"], -row["counted"], row["date"]))[:4],
        "weakest": sorted(rows, key=lambda row: (row["score"], -row["counted"], row["date"]))[:4],
        "minimum_counted_claims": 3,
    }


def _scope_summary(settings: Settings, manifest: dict) -> dict:
    scope = set(settings.audit_scope_categories)
    included = manifest.get("videos", [])
    excluded = manifest.get("excluded_videos", [])
    scoped_included = [video for video in included if video.get("category") in scope]
    scoped_excluded = [video for video in excluded if video.get("category") in scope]
    out_of_scope = [video for video in included + excluded if video.get("category") not in scope]
    counts = Counter(video.get("category") for video in scoped_included)
    return {
        "categories": list(settings.audit_scope_categories),
        "category_labels": [CATEGORY_LABELS.get(item, item) for item in settings.audit_scope_categories],
        "source_videos_found": len(included) + len(excluded),
        "videos_in_scope_found": len(scoped_included) + len(scoped_excluded),
        "videos_audited": len(scoped_included),
        "automatic_exclusions": len(scoped_excluded),
        "manual_exclusions": 0,
        "out_of_scope_videos": len(out_of_scope),
        "out_of_scope_categories": sorted({
            video.get("category") for video in out_of_scope if video.get("category")
        }),
        "category_counts": dict(counts),
        "price_outcome_only": settings.price_outcome_only,
    }


def build_dashboard_data(settings: Settings) -> dict:
    manifest = load_manifest(settings)
    if not manifest:
        return {
            "status": "waiting_for_manifest",
            "project_name": settings.project_name,
            "analyst_name": settings.analyst_name,
            "message": "Run collection and manifest stages first.",
            "channel": {"url": settings.youtube_channel_url, "id": settings.youtube_channel_id},
            "date_range": {"start": str(settings.start_date), "end": str(settings.end_date)},
        }

    summary_path = settings.pack_dir / "run_summary.json"
    run_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    verification = verify_audit_pack(settings)
    claims_path = settings.claims_dir / "extraction_run.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8")) if claims_path.exists() else None
    outcomes_path = settings.outcomes_dir / "claim_outcomes.json"
    outcomes = json.loads(outcomes_path.read_text(encoding="utf-8")) if outcomes_path.exists() else None
    scores_path = settings.scores_dir / "scoring_run.json"
    scores = json.loads(scores_path.read_text(encoding="utf-8")) if scores_path.exists() else None
    audit_summary = _score_presentation(scores)
    claim_rows = _read_jsonl(settings.claims_dir / "claims.jsonl")
    claims_by_id = {
        row["claim_id"]: row for row in claim_rows
        if isinstance(row.get("claim_id"), str)
    }
    outcome_summary = _outcome_presentation(outcomes, claims_by_id)
    pack_hashes = (run_summary or {}).get("pack_hashes", {})
    scope = _scope_summary(settings, manifest)
    scenario_profile = _scenario_presentation(
        claim_rows,
        set(settings.audit_scope_categories),
    )
    scoped_videos = [
        video for video in manifest.get("videos", [])
        if video.get("category") in set(settings.audit_scope_categories)
    ]
    synthetic_demo = any(
        isinstance(payload, dict) and bool(payload.get("synthetic_demo"))
        for payload in (claims, outcomes, scores)
    ) or "demo" in settings.project_name.casefold()
    human_review = get_human_review_status(settings)
    review_accepted = bool(human_review.get("accepted_for_current_artifacts"))
    publication = {
        "mode": settings.publication_mode,
        "requires_human_review": settings.publication_mode == "public",
        "human_review_accepted": review_accepted,
        "ready": settings.publication_mode == "public" and review_accepted,
        "public_claim_ledger": bool(
            settings.publication_mode == "public" and settings.public_claim_ledger
        ),
    }
    if not verification.get("verified"):
        status = "integrity_warning"
    elif scores and scores.get("status") == "complete":
        if settings.publication_mode == "public" and not review_accepted:
            status = "human_review_pending"
        elif settings.publication_mode == "public":
            status = "audit_complete"
        else:
            status = "private_preview"
    elif claims and claims.get("status") == "complete":
        status = "claims_complete"
    else:
        status = "collection_verified"

    verdict = audit_summary["conclusion_detail"] if audit_summary else None
    return {
        "status": status,
        "synthetic_demo": synthetic_demo,
        "project_name": settings.project_name,
        "analyst_name": manifest.get("channel", {}).get("analyst_name") or settings.analyst_name,
        "collection_id": manifest.get("collection_id", "legacy-collection"),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "channel": manifest.get("channel"),
        "date_range": manifest.get("date_range"),
        "summary": manifest.get("summary", {}),
        "scope": scope,
        "run_summary": run_summary,
        "verification": verification,
        "claims": claims,
        "outcomes": outcomes,
        "scores": scores,
        "audit_summary": audit_summary,
        "scenario_profile": scenario_profile,
        "outcome_summary": outcome_summary,
        "verdict": verdict,
        "result_examples": _result_examples(settings, scoped_videos) if scores else [],
        "video_highlights": _video_highlights(settings, scoped_videos) if scores else {"strongest": [], "weakest": []},
        "publication": publication,
        "human_review": {
            "status": human_review.get("status", "not_reviewed"),
            "ledger_valid": bool(human_review.get("ledger_valid")),
            "accepted_for_current_artifacts": review_accepted,
            "reviewed_at_utc": human_review.get("reviewed_at_utc"),
            "binding_sha256": human_review.get("binding_sha256"),
        },
        "tamper_evidence": {
            "manifest_sha256": pack_hashes.get("manifest_json_sha256"),
            "archive_sha256": (run_summary or {}).get("zip_sha256"),
            "market_evidence_sha256": (outcome_summary or {}).get("market_evidence_snapshot_sha256"),
            "outcome_sha256": (outcome_summary or {}).get("snapshot_sha256"),
            "file_hash_count": verification.get("file_hash_count", 0),
            "verification_status": verification.get("status", "not_available"),
        },
        "limitations": [
            "Videos outside AUDIT_SCOPE_CATEGORIES remain visible in the source ledger but do not enter the score.",
            "Context inputs such as liquidation maps, ETF flows, and macro explanations are not independently audited.",
            "Binance one-minute spot data is the crypto benchmark; another venue may differ at borderline levels.",
            "International outcomes use either operator-provided CSV data or explicitly labelled Yahoo proxies.",
            "Recent videos whose 24-hour window has not elapsed remain insufficient evidence.",
            "AI-assisted extraction and scoring require human review and are not objective ground truth.",
        ],
    }


def write_dashboard_data(settings: Settings) -> Path:
    invalidate_publication_snapshot(settings)
    data = build_dashboard_data(settings)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    out = settings.reports_dir / "dashboard_data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
