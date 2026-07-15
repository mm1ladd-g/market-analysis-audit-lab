from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from audit_lab.models.scoring import ClaimScoreCandidate, ModelVideoScoring
from audit_lab.settings import Settings
from audit_lab.stages.extract_claims import (
    CLAIM_SCHEMA_VERSION,
    EVIDENCE_POLICY,
    normalize_horizon_hours,
    usage_payload,
)
from audit_lab.stages.extract_claims import PROMPT_PATH as CLAIM_PROMPT_PATH
from audit_lab.utils.hash import sha256_json, sha256_text
from audit_lab.utils.jsonio import append_json_line, write_json_atomic, write_text_atomic

SCORING_SCHEMA_VERSION = "3.0.0"
SCORING_POLICY = "single-window-complete-all-assets-trigger-contract-v3"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "scoring_system.md"
COUNTED_RESULTS = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}


class ScoringContractError(ValueError):
    pass


VOLATILE_OUTCOME_KEYS = {"source_file", "source_sha256"}


def _stable_outcome(value):
    """Remove storage-location metadata that cannot change a scoring decision."""
    if isinstance(value, dict):
        return {
            key: _stable_outcome(item)
            for key, item in value.items()
            if key not in VOLATILE_OUTCOME_KEYS
        }
    if isinstance(value, list):
        return [_stable_outcome(item) for item in value]
    return value


def scoring_input_fingerprint(
    *,
    settings: Settings,
    prompt_sha256: str,
    video: dict,
    claims: list[dict],
    outcomes: list[dict],
) -> str:
    """Key model judgment to immutable evidence, not to a collection container ID."""
    return sha256_json({
        "schema_version": SCORING_SCHEMA_VERSION,
        "scoring_policy": SCORING_POLICY,
        "model": settings.openai_scoring_model,
        "reasoning_effort": settings.openai_scoring_reasoning_effort,
        "prompt_sha256": prompt_sha256,
        "video": video["video_id"],
        "claims": claims,
        "outcomes": _stable_outcome(outcomes),
    })


def estimate_scoring_cost_usd(usage: dict, settings: Settings) -> float | None:
    input_rate = settings.openai_scoring_input_usd_per_1m
    output_rate = settings.openai_scoring_output_usd_per_1m
    if input_rate is None or output_rate is None:
        return None
    cached_rate = settings.openai_scoring_cached_input_usd_per_1m
    if cached_rate is None:
        cached_rate = input_rate
    cached = min(usage["cached_input_tokens"], usage["input_tokens"])
    regular = usage["input_tokens"] - cached
    return round((regular * input_rate + cached * cached_rate + usage["output_tokens"] * output_rate) / 1_000_000, 8)


def required_evaluation_window(claim: dict) -> str | None:
    """Return the sole supported contract window, or None for an unsupported horizon."""
    stated = claim.get("time_horizon")
    declared = claim.get("normalized_horizon_hours")
    if stated is not None and str(stated).strip():
        normalized = normalize_horizon_hours(str(stated))
        if normalized not in {24, 48}:
            return None
        if declared is not None and declared != normalized:
            return None
        return f"{normalized}h"
    if declared is not None:
        # A normalized value without cited horizon text is not canonical evidence.
        return None
    return "24h"


def outcome_supports_window(outcome: dict, evaluation_window: str) -> bool:
    """Every material asset must have the same selected complete window."""
    window_key = {"24h": "window_24h", "48h": "window_48h"}.get(evaluation_window)
    if window_key is None:
        return False
    assets = outcome.get("assets", [])
    if not assets:
        return False
    return all(
        asset.get("status") == "available"
        and asset.get(window_key, {}).get("complete") is True
        for asset in assets
    )


def deterministic_exclusion(claim: dict, outcome: dict) -> ClaimScoreCandidate | None:
    """Return exclusions that do not require interpretive model judgment."""
    if claim["scoreability"] == "not_scoreable":
        return ClaimScoreCandidate(
            claim_id=claim["claim_id"],
            result="not_scoreable",
            score=0,
            counts_in_final_score=False,
            trigger_status="not_applicable",
            data_sufficiency="sufficient",
            evidence_summary="The extraction stage classified this claim as not scoreable.",
            reasoning=claim.get("not_scoreable_reason") or "The claim lacks a measurable scoring contract.",
            evaluation_window=None,
            scoring_confidence=1,
        )
    evaluation_window = required_evaluation_window(claim)
    if evaluation_window is None:
        return ClaimScoreCandidate(
            claim_id=claim["claim_id"],
            result="not_scoreable",
            score=0,
            counts_in_final_score=False,
            trigger_status="not_applicable",
            data_sufficiency="sufficient",
            evidence_summary="The claim's stated horizon does not map to a supported audit window.",
            reasoning="Only explicit 24-hour and 48-hour horizons are normalized; horizon-free daily claims use the documented 24-hour default.",
            evaluation_window=None,
            scoring_confidence=1,
        )
    if outcome_supports_window(outcome, evaluation_window):
        return None

    assets = outcome.get("assets", [])
    statuses = {asset.get("status") for asset in assets}
    if assets and statuses <= {"out_of_scope_non_price"}:
        return ClaimScoreCandidate(
            claim_id=claim["claim_id"],
            result="not_scoreable",
            score=0,
            counts_in_final_score=False,
            trigger_status="not_applicable",
            data_sufficiency="sufficient",
            evidence_summary="This claim tests a contextual input rather than a subsequent market-price outcome.",
            reasoning="The configured audit measures price-analysis performance and does not independently score ETF-flow, liquidation, or macro-context facts.",
            evaluation_window=None,
            scoring_confidence=1,
        )
    if assets and statuses <= {"unsupported_asset"}:
        data_sufficiency = "unsupported_asset"
        evidence = "Every identified asset lacks a configured defensible market-data source."
    elif any(asset.get("status") == "available" for asset in assets):
        data_sufficiency = "partial"
        evidence = f"Market data exists, but the required {evaluation_window} outcome window is not complete for every asset."
    elif assets:
        data_sufficiency = "insufficient"
        evidence = "No complete usable market series is available for the identified assets."
    else:
        data_sufficiency = "insufficient"
        evidence = "The extracted claim has no asset that can be matched to market data."
    return ClaimScoreCandidate(
        claim_id=claim["claim_id"],
        result="insufficient_data",
        score=0,
        counts_in_final_score=False,
        trigger_status="unclear" if claim["scoreability"] == "conditional_scoreable" else "not_applicable",
        data_sufficiency=data_sufficiency,
        evidence_summary=evidence,
        reasoning=f"Application policy requires the same complete {evaluation_window} window for every material asset.",
        evaluation_window=evaluation_window,
        scoring_confidence=1,
    )


def validate_video_scoring(parsed: ModelVideoScoring, video_id: str, claims: list[dict], outcomes: dict[str, dict]) -> None:
    if parsed.video_id != video_id:
        raise ScoringContractError("Scoring response video_id does not match the request")
    expected = [claim["claim_id"] for claim in claims]
    returned = [score.claim_id for score in parsed.scores]
    if len(returned) != len(set(returned)) or set(returned) != set(expected):
        raise ScoringContractError("Scoring response must contain every claim ID exactly once")
    claim_by_id = {claim["claim_id"]: claim for claim in claims}
    for score in parsed.scores:
        claim = claim_by_id[score.claim_id]
        outcome = outcomes.get(score.claim_id)
        if outcome is None:
            raise ScoringContractError(f"No outcome evidence exists for {score.claim_id}")
        evaluation_window = required_evaluation_window(claim)
        if claim["scoreability"] == "not_scoreable" and (
            score.result != "not_scoreable" or score.counts_in_final_score or score.score != 0
        ):
            raise ScoringContractError("Not-scoreable input claims cannot enter the final score")
        if claim["scoreability"] == "scoreable" and score.trigger_status != "not_applicable":
            raise ScoringContractError("Direct claims must use not_applicable trigger status")
        if score.result in COUNTED_RESULTS:
            if not score.counts_in_final_score or score.score != COUNTED_RESULTS[score.result]:
                raise ScoringContractError("Counted result and fixed score are inconsistent")
            if score.data_sufficiency != "sufficient":
                raise ScoringContractError("A counted claim requires sufficient data")
            if evaluation_window is None or score.evaluation_window != evaluation_window:
                raise ScoringContractError("A counted claim must use its machine-selected evaluation window")
            if not outcome_supports_window(outcome, evaluation_window):
                raise ScoringContractError("Every asset needs the same selected complete market window")
            if claim["scoreability"] == "conditional_scoreable" and score.trigger_status != "triggered":
                raise ScoringContractError("A counted conditional claim requires a verified triggered status")
        elif score.counts_in_final_score or score.score != 0:
            raise ScoringContractError("Non-counted result must have score 0 and be excluded")
        if score.result == "not_triggered":
            if score.trigger_status != "not_triggered":
                raise ScoringContractError("Not-triggered result requires not-triggered status")
            if claim["scoreability"] != "conditional_scoreable":
                raise ScoringContractError("Only conditional claims can receive a not-triggered result")
            if score.data_sufficiency != "sufficient":
                raise ScoringContractError("Not-triggered requires sufficient trigger evidence")
            if evaluation_window is None or score.evaluation_window != evaluation_window:
                raise ScoringContractError("Not-triggered must use the machine-selected evaluation window")
            if not outcome_supports_window(outcome, evaluation_window):
                raise ScoringContractError("Not-triggered requires the selected complete window for every asset")
        if score.result == "insufficient_data" and score.data_sufficiency == "sufficient":
            raise ScoringContractError("Insufficient-data results cannot claim sufficient evidence")
        if score.result == "not_scoreable" and score.evaluation_window is not None:
            raise ScoringContractError("Not-scoreable results cannot select an outcome window")


def validate_score_artifact(
    artifact: dict,
    video: dict,
    claims: list[dict],
    outcomes: dict[str, dict],
) -> ModelVideoScoring:
    raw_scores = artifact.get("scores", [])
    if not isinstance(raw_scores, list):
        raise ScoringContractError("Score artifact scores must be an array")
    expected_metadata = {
        "video_id": video["video_id"],
        "upload_date": video.get("upload_date"),
        "category": video.get("category"),
    }
    for raw in raw_scores:
        if not isinstance(raw, dict):
            raise ScoringContractError("Score artifact contains a non-object score")
        if any(raw.get(key) != value for key, value in expected_metadata.items()):
            raise ScoringContractError("Score artifact contains non-canonical video metadata")
    parsed = ModelVideoScoring(
        video_id=video["video_id"],
        scores=[
            ClaimScoreCandidate.model_validate({
                key: value
                for key, value in score.items()
                if key in ClaimScoreCandidate.model_fields
            })
            for score in raw_scores
        ],
        scoring_notes=artifact.get("scoring_notes", []),
    )
    validate_video_scoring(parsed, video["video_id"], claims, outcomes)
    return parsed


def _is_retriable(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError, ScoringContractError)):
        return True
    return isinstance(exc, APIStatusError) and (exc.status_code in {408, 409, 429} or exc.status_code >= 500)


def _request_input(video: dict, claims: list[dict], outcomes: list[dict]) -> str:
    claims_with_contract = [
        {
            **claim,
            "evaluation_window_required": required_evaluation_window(claim),
        }
        for claim in claims
    ]
    payload = {
        "video": {
            "video_id": video["video_id"],
            "upload_date": video["upload_date"],
            "published_at_utc": video.get("published_at_utc"),
            "category": video["category"],
            "title": video["title"],
        },
        "claims": claims_with_contract,
        "market_outcomes": outcomes,
    }
    return "AUTHORITATIVE AUDIT INPUT:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _score_one(
    *,
    client: OpenAI,
    settings: Settings,
    collection_id: str,
    video: dict,
    claims: list[dict],
    outcomes: list[dict],
    prompt: str,
    cache_key: str,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[dict, int]:
    failed_attempts = 0
    outcome_by_id = {item["claim_id"]: item for item in outcomes}
    for attempt in range(settings.openai_max_retries + 1):
        try:
            response = client.responses.parse(
                model=settings.openai_scoring_model,
                instructions=prompt,
                input=_request_input(video, claims, outcomes),
                text_format=ModelVideoScoring,
                reasoning={"effort": settings.openai_scoring_reasoning_effort},
                store=False,
                metadata={
                    "project": "market-analysis-audit-lab",
                    "collection_id": collection_id,
                    "video_id": video["video_id"],
                    "schema_version": SCORING_SCHEMA_VERSION,
                },
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                raise ScoringContractError("The API returned no parsed scoring output")
            validate_video_scoring(parsed, video["video_id"], claims, outcome_by_id)
            usage = usage_payload(response)
            scores = [
                {
                    **candidate.model_dump(mode="json"),
                    "video_id": video["video_id"],
                    "upload_date": video["upload_date"],
                    "category": video["category"],
                }
                for candidate in parsed.scores
            ]
            artifact = {
                "schema_version": SCORING_SCHEMA_VERSION,
                "collection_id": collection_id,
                "cache_key": cache_key,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "video_id": video["video_id"],
                "upload_date": video["upload_date"],
                "category": video["category"],
                "title": video["title"],
                "requested_model": settings.openai_scoring_model,
                "response_model": getattr(response, "model", settings.openai_scoring_model),
                "response_id": getattr(response, "id", None),
                "usage": usage,
                "estimated_cost_usd": estimate_scoring_cost_usd(usage, settings),
                "scoring_notes": parsed.scoring_notes,
                "scores": scores,
            }
            append_json_line(settings.logs_dir / "scoring.jsonl", {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "event": "api_success",
                "video_id": video["video_id"],
                "attempt": attempt + 1,
                "response_id": artifact["response_id"],
                "usage": usage,
            })
            return artifact, failed_attempts
        except Exception as exc:
            failed_attempts += 1
            retriable = _is_retriable(exc) and attempt < settings.openai_max_retries
            append_json_line(settings.logs_dir / "scoring.jsonl", {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "event": "api_failure",
                "video_id": video["video_id"],
                "attempt": attempt + 1,
                "error_type": type(exc).__name__,
                "retriable": retriable,
            })
            if not retriable:
                raise
            sleep_fn(min(2 ** attempt, 8))
    raise RuntimeError("Scoring retry loop ended unexpectedly")


def _aggregate(scores: list[dict]) -> dict:
    counts = Counter(score["result"] for score in scores)
    counted = [score for score in scores if score["counts_in_final_score"]]
    final_score = None if not counted else round(sum(score["score"] for score in counted) / len(counted) * 100, 2)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for score in scores:
        by_category[score["category"]].append(score)
    category_breakdown = {}
    for category, items in sorted(by_category.items()):
        category_counted = [item for item in items if item["counts_in_final_score"]]
        category_breakdown[category] = {
            "total_claims": len(items),
            "counted_claims": len(category_counted),
            "score": None if not category_counted else round(sum(item["score"] for item in category_counted) / len(category_counted) * 100, 2),
            "results": dict(Counter(item["result"] for item in items)),
        }
    return {
        "total_claims": len(scores),
        "counted_claims": len(counted),
        "final_score": final_score,
        "results": dict(counts),
        "category_breakdown": category_breakdown,
    }


def _unique_items_by_id(items: list[dict], key: str, label: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for item in items:
        identifier = item.get(key)
        if not isinstance(identifier, str) or not identifier:
            raise SystemExit(f"{label} contains an item without {key}.")
        if identifier in indexed:
            raise SystemExit(f"{label} contains duplicate {key}: {identifier}")
        indexed[identifier] = item
    return indexed


def run_scoring(
    settings: Settings,
    *,
    limit: int | None = None,
    video_ids: list[str] | None = None,
    force: bool = False,
    client: OpenAI | None = None,
) -> Path:
    manifest = json.loads((settings.pack_dir / "manifest.json").read_text(encoding="utf-8"))
    extraction = json.loads((settings.claims_dir / "extraction_run.json").read_text(encoding="utf-8"))
    outcomes_payload = json.loads((settings.outcomes_dir / "claim_outcomes.json").read_text(encoding="utf-8"))
    collection_id = manifest["collection_id"]
    if extraction.get("collection_id") != collection_id or extraction.get("status") != "complete":
        raise SystemExit("Complete claims for the current collection are required.")
    expected_extraction_metadata = {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "evidence_policy": EVIDENCE_POLICY,
        "model": settings.openai_claim_model,
        "reasoning_effort": settings.openai_claim_reasoning_effort,
        "prompt_sha256": sha256_text(CLAIM_PROMPT_PATH.read_text(encoding="utf-8")),
    }
    if any(extraction.get(key) != value for key, value in expected_extraction_metadata.items()):
        raise SystemExit("Claim extraction metadata does not match the current extraction contract.")
    if outcomes_payload.get("collection_id") != collection_id:
        raise SystemExit("Outcome data does not belong to the current collection.")

    scope = set(settings.audit_scope_categories)
    eligible_videos = [
        video for video in manifest.get("videos", [])
        if video.get("category") in scope and video.get("transcript_txt")
    ]
    eligible_video_ids = [video["video_id"] for video in eligible_videos]
    if len(eligible_video_ids) != len(set(eligible_video_ids)):
        raise SystemExit("Manifest contains duplicate audit-eligible video IDs.")

    claims_by_video: dict[str, list[dict]] = {}
    all_claim_ids: set[str] = set()
    for video in eligible_videos:
        path = settings.claims_dir / f"{video['video_id']}.claims.json"
        if not path.is_file():
            raise SystemExit(f"Missing exact claim artifact for {video['video_id']}")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if (
            artifact.get("collection_id") != collection_id
            or artifact.get("video_id") != video["video_id"]
            or artifact.get("transcript_sha256") != video.get("transcript_sha256")
            or artifact.get("schema_version") != extraction["schema_version"]
            or artifact.get("evidence_policy") != extraction["evidence_policy"]
            or artifact.get("prompt_sha256") != extraction["prompt_sha256"]
            or artifact.get("requested_model") != extraction["model"]
            or artifact.get("reasoning_effort") != extraction["reasoning_effort"]
        ):
            raise SystemExit(f"Claim artifact mismatch for {video['video_id']}")
        claims = artifact.get("claims", [])
        indexed_claims = _unique_items_by_id(claims, "claim_id", f"Claim artifact {video['video_id']}")
        duplicate_global = all_claim_ids & set(indexed_claims)
        if duplicate_global:
            raise SystemExit("Claim IDs must be globally unique: " + ", ".join(sorted(duplicate_global)))
        all_claim_ids.update(indexed_claims)
        claims_by_video[video["video_id"]] = claims

    outcome_rows = outcomes_payload.get("claims", [])
    if not isinstance(outcome_rows, list):
        raise SystemExit("Outcome claim ledger must be an array.")
    outcomes_by_claim = _unique_items_by_id(outcome_rows, "claim_id", "Outcome claim ledger")
    if set(outcomes_by_claim) != all_claim_ids:
        missing = sorted(all_claim_ids - set(outcomes_by_claim))
        extra = sorted(set(outcomes_by_claim) - all_claim_ids)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise SystemExit("Outcome ledger does not exactly match current claims (" + "; ".join(details) + ").")

    videos = eligible_videos
    if video_ids:
        requested = set(video_ids)
        known = {video["video_id"] for video in videos}
        if requested - known:
            raise SystemExit("Unknown or excluded video IDs: " + ", ".join(sorted(requested - known)))
        videos = [video for video in videos if video["video_id"] in requested]
    if limit is not None:
        if limit < 1:
            raise SystemExit("--limit must be at least 1")
        videos = videos[:limit]

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    prompt_sha256 = sha256_text(prompt)
    cache_root = settings.cache_dir / "scoring"
    settings.scores_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    for video in videos:
        claims = claims_by_video[video["video_id"]]
        claim_outcomes = [outcomes_by_claim[claim["claim_id"]] for claim in claims]
        deterministic_scores = {}
        ai_claims = []
        ai_outcomes = []
        for claim, outcome in zip(claims, claim_outcomes, strict=True):
            excluded = deterministic_exclusion(claim, outcome)
            if excluded is None:
                ai_claims.append(claim)
                ai_outcomes.append(outcome)
            else:
                deterministic_scores[claim["claim_id"]] = {
                    **excluded.model_dump(mode="json"),
                    "video_id": video["video_id"],
                    "upload_date": video["upload_date"],
                    "category": video["category"],
                }
        cache_key = scoring_input_fingerprint(
            settings=settings,
            prompt_sha256=prompt_sha256,
            video=video,
            claims=claims,
            outcomes=claim_outcomes,
        )
        cache_path = cache_root / f"{video['video_id']}__{cache_key}.json"
        cached = None
        candidate_paths = [cache_path, settings.scores_dir / f"{video['video_id']}.scores.json"]
        if not force:
            for candidate_path in candidate_paths:
                if not candidate_path.exists():
                    continue
                try:
                    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError, TypeError):
                    continue
                if (
                    candidate.get("scoring_input_fingerprint") != cache_key
                    or candidate.get("schema_version") != SCORING_SCHEMA_VERSION
                    or candidate.get("scoring_policy") != SCORING_POLICY
                    or candidate.get("prompt_sha256") != prompt_sha256
                    or candidate.get("requested_model") != settings.openai_scoring_model
                    or candidate.get("reasoning_effort") != settings.openai_scoring_reasoning_effort
                    or candidate.get("video_id") != video["video_id"]
                ):
                    continue
                try:
                    validate_score_artifact(candidate, video, claims, outcomes_by_claim)
                except (ScoringContractError, ValueError, TypeError, KeyError):
                    continue
                if candidate.get("collection_id") != collection_id:
                    candidate = dict(candidate)
                    candidate["api_collection_id"] = candidate.get("api_collection_id") or candidate.get("collection_id")
                    candidate["collection_id"] = collection_id
                    candidate["rebased_at_utc"] = datetime.now(timezone.utc).isoformat()
                candidate["cache_key"] = cache_key
                candidate["scoring_input_fingerprint"] = cache_key
                cached = candidate
                break
        jobs.append({
            "video": video,
            "claims": claims,
            "claim_outcomes": claim_outcomes,
            "ai_claims": ai_claims,
            "ai_outcomes": ai_outcomes,
            "deterministic_scores": deterministic_scores,
            "cache_key": cache_key,
            "cache_path": cache_path,
            "cached": cached,
        })

    needs_api = any(job["ai_claims"] and job["cached"] is None for job in jobs)
    if needs_api and client is None:
        settings.require_openai_configuration()
        client = OpenAI(api_key=settings.openai_api_key_value, max_retries=0, timeout=settings.openai_timeout_seconds)

    cache_hits = successful_calls = failed_attempts = 0
    run_usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    run_costs: list[float | None] = []
    api_jobs = []
    for job in jobs:
        video = job["video"]
        claims = job["claims"]
        if job["cached"] is not None:
            artifact = job["cached"]
            cache_hits += 1
            write_json_atomic(job["cache_path"], artifact)
        elif not job["ai_claims"]:
            artifact = {
                "schema_version": SCORING_SCHEMA_VERSION,
                "scoring_policy": SCORING_POLICY,
                "collection_id": collection_id,
                "cache_key": job["cache_key"],
                "scoring_input_fingerprint": job["cache_key"],
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "video_id": video["video_id"],
                "upload_date": video["upload_date"],
                "category": video["category"],
                "title": video["title"],
                "requested_model": settings.openai_scoring_model,
                "reasoning_effort": settings.openai_scoring_reasoning_effort,
                "prompt_sha256": prompt_sha256,
                "response_model": None,
                "response_id": None,
                "usage": {key: 0 for key in run_usage},
                "estimated_cost_usd": 0.0,
                "scoring_notes": ["All claims were excluded by deterministic application rules; no model judgment was used."],
                "scores": [job["deterministic_scores"][claim["claim_id"]] for claim in claims],
            }
            write_json_atomic(job["cache_path"], artifact)
        else:
            api_jobs.append(job)
            continue
        write_json_atomic(settings.scores_dir / f"{video['video_id']}.scores.json", artifact)

    scoring_errors = []
    if api_jobs:
        assert client is not None
        workers = min(settings.openai_concurrency, len(api_jobs))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="claim-scoring") as executor:
            futures = {
                executor.submit(
                    _score_one,
                    client=client,
                    settings=settings,
                    collection_id=collection_id,
                    video=job["video"],
                    claims=job["ai_claims"],
                    outcomes=job["ai_outcomes"],
                    prompt=prompt,
                    cache_key=job["cache_key"],
                ): job
                for job in api_jobs
            }
            for future in as_completed(futures):
                job = futures[future]
                video = job["video"]
                try:
                    artifact, failures = future.result()
                    model_scores = {score["claim_id"]: score for score in artifact["scores"]}
                    combined = {**job["deterministic_scores"], **model_scores}
                    artifact["schema_version"] = SCORING_SCHEMA_VERSION
                    artifact["scoring_policy"] = SCORING_POLICY
                    artifact["scoring_input_fingerprint"] = job["cache_key"]
                    artifact["reasoning_effort"] = settings.openai_scoring_reasoning_effort
                    artifact["prompt_sha256"] = prompt_sha256
                    artifact["scores"] = [combined[claim["claim_id"]] for claim in job["claims"]]
                    artifact["scoring_notes"] = [
                        *artifact.get("scoring_notes", []),
                        f"{len(job['deterministic_scores'])} claim(s) were excluded by application rules before model evaluation.",
                    ]
                    parsed = ModelVideoScoring(
                        video_id=video["video_id"],
                        scores=[
                            ClaimScoreCandidate.model_validate({
                                key: value for key, value in score.items()
                                if key in ClaimScoreCandidate.model_fields
                            })
                            for score in artifact["scores"]
                        ],
                        scoring_notes=artifact["scoring_notes"],
                    )
                    validate_video_scoring(
                        parsed,
                        video["video_id"],
                        job["claims"],
                        {item["claim_id"]: item for item in job["claim_outcomes"]},
                    )
                except Exception as exc:
                    scoring_errors.append({
                        "video_id": video["video_id"],
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    })
                    continue
                failed_attempts += failures
                successful_calls += 1
                for key in run_usage:
                    run_usage[key] += artifact["usage"][key]
                run_costs.append(artifact.get("estimated_cost_usd"))
                write_json_atomic(job["cache_path"], artifact)
                write_json_atomic(settings.scores_dir / f"{video['video_id']}.scores.json", artifact)

    all_artifacts = []
    eligible_ids = {video["video_id"] for video in eligible_videos}
    for video in eligible_videos:
        path = settings.scores_dir / f"{video['video_id']}.scores.json"
        if not path.is_file():
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        claims = claims_by_video[video["video_id"]]
        claim_outcomes = [outcomes_by_claim[claim["claim_id"]] for claim in claims]
        expected_fingerprint = scoring_input_fingerprint(
            settings=settings,
            prompt_sha256=prompt_sha256,
            video=video,
            claims=claims,
            outcomes=claim_outcomes,
        )
        if (
            artifact.get("collection_id") != collection_id
            or artifact.get("video_id") != video["video_id"]
            or artifact.get("schema_version") != SCORING_SCHEMA_VERSION
            or artifact.get("scoring_policy") != SCORING_POLICY
            or artifact.get("scoring_input_fingerprint") != expected_fingerprint
            or artifact.get("prompt_sha256") != prompt_sha256
            or artifact.get("requested_model") != settings.openai_scoring_model
            or artifact.get("reasoning_effort") != settings.openai_scoring_reasoning_effort
        ):
            continue
        try:
            validate_score_artifact(
                artifact,
                video,
                claims,
                {item["claim_id"]: item for item in claim_outcomes},
            )
        except (ScoringContractError, ValueError, TypeError):
            continue
        all_artifacts.append(artifact)
    all_scores = [score for artifact in all_artifacts for score in artifact.get("scores", [])]
    total_usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for artifact in all_artifacts:
        for key in total_usage:
            total_usage[key] += int(artifact.get("usage", {}).get(key, 0) or 0)
    write_text_atomic(
        settings.scores_dir / "scores.jsonl",
        "".join(json.dumps(score, ensure_ascii=False, separators=(",", ":")) + "\n" for score in all_scores),
    )
    completed_ids = {artifact["video_id"] for artifact in all_artifacts}
    aggregate = _aggregate(all_scores)
    artifact_costs = [artifact.get("estimated_cost_usd") for artifact in all_artifacts]
    total_cost = None if any(value is None for value in artifact_costs) else round(sum(artifact_costs), 8)
    run_cost = None if any(value is None for value in run_costs) else round(sum(run_costs), 8)
    summary = {
        "schema_version": SCORING_SCHEMA_VERSION,
        "scoring_policy": SCORING_POLICY,
        "scoring_run_id": f"score-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{sha256_json(sorted(completed_ids))[:8]}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if completed_ids == eligible_ids else "partial",
        "collection_id": collection_id,
        "model": settings.openai_scoring_model,
        "audit_scope_categories": list(settings.audit_scope_categories),
        "price_outcome_only": settings.price_outcome_only,
        "prompt_sha256": prompt_sha256,
        "eligible_videos": len(eligible_ids),
        "completed_videos": len(completed_ids),
        "selected_videos_this_run": len(videos),
        "cache_hits_this_run": cache_hits,
        "successful_api_calls_this_run": successful_calls,
        "failed_or_retried_calls_this_run": failed_attempts,
        "failed_videos_this_run": scoring_errors,
        "concurrency": settings.openai_concurrency,
        "api_calls_this_run": successful_calls + failed_attempts,
        "usage_this_run": run_usage,
        "usage_all_artifacts": total_usage,
        "api_response_artifacts": sum(bool(artifact.get("response_id")) for artifact in all_artifacts),
        "estimated_cost_usd_this_run": run_cost,
        "estimated_cost_usd_all_artifacts": total_cost,
        "pricing_configured": total_cost is not None,
        "cost_scope": "accepted response artifacts only; failed attempts are not included because the API response did not expose usage",
        **aggregate,
    }
    out = settings.scores_dir / "scoring_run.json"
    write_json_atomic(out, summary)
    if scoring_errors:
        raise SystemExit(
            f"Scoring failed for {len(scoring_errors)} video(s); successful artifacts were cached. "
            "Re-run to retry failures."
        )
    return out
