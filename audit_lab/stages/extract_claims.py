from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from audit_lab.models.claims import ClaimCandidate, ModelClaimExtraction
from audit_lab.settings import Settings
from audit_lab.utils.hash import sha256_file, sha256_json, sha256_text
from audit_lab.utils.jsonio import append_json_line, read_json, write_json_atomic, write_text_atomic

CLAIM_SCHEMA_VERSION = "claim-extraction-v4"
EVIDENCE_POLICY = "bounded-canonical-lines-and-bound-numeric-levels-v2"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "claim_extraction_system.md"
MAX_EVIDENCE_LINES = 8
MAX_EVIDENCE_CHARACTERS = 2000
REVIEW_REQUIRED_FIELDS = [
    "claim_text",
    "claim_type",
    "assets",
    "levels",
    "direction",
    "condition",
    "invalidation_condition",
    "time_horizon",
    "scoreability",
]

_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_NUMBER_RE = re.compile(
    r"(?<![\w])[-+]?(?:\d{1,3}(?:[,\u066c]\d{3})+|\d+)(?:[.\u066b]\d+)?(?![\w])",
    flags=re.UNICODE,
)
_NON_PRICE_LEVEL_RE = re.compile(
    r"(?:%|percent|percentage|درصد|ساعت|ساعة|hours?|hrs?|days?|روز|يوم|years?|سال)",
    flags=re.IGNORECASE,
)
_INSTRUCTION_LIKE_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?(?:previous|prior|system)|system\s+prompt|developer\s+message|"
    r"return\s+(?:only\s+)?json|output\s+schema|api\s*key|"
    r"دستور(?:های)?\s+(?:قبلی|سیستم)|پرامپت\s+سیستم|کلید\s*(?:ای\s*پی\s*آی|api))",
    flags=re.IGNORECASE,
)


class ClaimEvidenceError(ValueError):
    """Raised when structured output does not trace back to the supplied transcript."""


def line_numbered_transcript(transcript: str) -> str:
    return "\n".join(f"L{index:04d}: {line}" for index, line in enumerate(transcript.splitlines(), start=1))


def _normalize_evidence(value: str) -> str:
    value = value.replace("\u200c", " ")
    return re.sub(r"\s+", " ", value).strip()


def _strip_line_prefixes(value: str) -> str:
    return re.sub(r"(?m)^\s*L\d{4}:\s*", "", value)


def _evidence_tokens(value: str) -> Counter[str]:
    normalized = _normalize_evidence(_strip_line_prefixes(value)).lower()
    return Counter(re.findall(r"[\w\u0600-\u06ff]+", normalized, flags=re.UNICODE))


def _evidence_coverage(excerpt: str, selected: str) -> float:
    excerpt_tokens = _evidence_tokens(excerpt)
    if not excerpt_tokens:
        return 0.0
    selected_tokens = _evidence_tokens(selected)
    if not selected_tokens:
        return 0.0
    matched = sum((excerpt_tokens & selected_tokens).values())
    # Either side may include adjacent context. What matters is that the
    # shorter passage is substantially contained in the other passage.
    return matched / min(sum(excerpt_tokens.values()), sum(selected_tokens.values()))


def normalize_horizon_hours(value: str | None) -> int | None:
    """Normalize only the two outcome horizons the public methodology supports."""
    if value is None or not value.strip():
        return None
    text = _normalize_evidence(value.translate(_DIGIT_TRANSLATION)).lower()
    if re.search(r"(?<!\d)24\s*(?:-|–|—|to|تا)\s*48(?!\d)", text, flags=re.IGNORECASE):
        return None
    matches: set[int] = set()
    patterns = {
        24: (
            r"(?<!\d)24\s*(?:h(?:ours?)?|hrs?|ساعت|ساعة)(?!\w)",
            r"(?<!\d)1\s*(?:d(?:ays?)?|روز(?:ه)?|يوم)(?!\w)",
            r"\b(?:today|tomorrow|daily|intraday|one[ -]day|next\s+(?:trading\s+)?day|same\s+day)\b",
            r"(?:امروز|فردا|روزانه|درون\s*روزی|تا\s*فردا|یک\s*روز|يوم\s*واحد)",
        ),
        48: (
            r"(?<!\d)48\s*(?:h(?:ours?)?|hrs?|ساعت|ساعة)(?!\w)",
            r"(?<!\d)2\s*(?:d(?:ays?)?|روز(?:ه)?|يوم)(?!\w)",
            r"\b(?:two[ -]days?|next\s+two\s+days)\b",
            r"(?:دو\s*روز(?:ه)?|پس\s*فردا|يومين)",
        ),
    }
    for hours, variants in patterns.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in variants):
            matches.add(hours)
    return next(iter(matches)) if len(matches) == 1 else None


def _numeric_tokens(value: str) -> set[str]:
    normalized = value.translate(_DIGIT_TRANSLATION)
    tokens: set[str] = set()
    for match in _NUMBER_RE.finditer(normalized):
        raw = match.group(0).replace(",", "").replace("\u066c", "").replace("\u066b", ".")
        try:
            number = Decimal(raw)
        except InvalidOperation:
            continue
        tokens.add(format(number.normalize(), "f"))
    return tokens


def _apply_review_policy(claim: ClaimCandidate, selected: str) -> None:
    normalized_horizon = normalize_horizon_hours(claim.time_horizon)
    flags = {"ai_semantic_interpretation"}
    if _INSTRUCTION_LIKE_RE.search(selected):
        flags.add("instruction_like_source_text")
    if claim.time_horizon and normalized_horizon is None:
        flags.add("unsupported_time_horizon")
        claim.scoreability = "not_scoreable"
        claim.not_scoreable_reason = (
            "The stated horizon cannot be normalized to the supported 24-hour or 48-hour audit window."
        )
    claim.normalized_horizon_hours = normalized_horizon
    claim.human_review_required = True
    claim.review_required_fields = list(REVIEW_REQUIRED_FIELDS)
    claim.review_flags = sorted(flags)


def validate_extraction(result: ModelClaimExtraction, video_id: str, transcript: str) -> None:
    if result.video_id != video_id:
        raise ClaimEvidenceError(f"Model returned video_id={result.video_id!r}, expected {video_id!r}")

    lines = transcript.splitlines()
    for index, claim in enumerate(result.claims, start=1):
        if claim.source_line_end < claim.source_line_start:
            raise ClaimEvidenceError(f"Claim {index} has a reversed line range")
        if claim.source_line_end > len(lines):
            raise ClaimEvidenceError(f"Claim {index} cites a line outside the transcript")
        if claim.source_line_end - claim.source_line_start + 1 > MAX_EVIDENCE_LINES:
            raise ClaimEvidenceError(
                f"Claim {index} cites more than {MAX_EVIDENCE_LINES} consecutive evidence lines"
            )
        selected = "\n".join(lines[claim.source_line_start - 1:claim.source_line_end])
        if len(selected) > MAX_EVIDENCE_CHARACTERS:
            raise ClaimEvidenceError(
                f"Claim {index} evidence exceeds {MAX_EVIDENCE_CHARACTERS} characters"
            )
        advisory_excerpt = _strip_line_prefixes(claim.source_excerpt)
        exact_match = _normalize_evidence(advisory_excerpt) in _normalize_evidence(selected)
        if not exact_match and _evidence_coverage(advisory_excerpt, selected) < 0.72:
            raise ClaimEvidenceError(f"Claim {index} excerpt does not match its cited line range")
        # The model selects the evidence range; the application, not the model,
        # writes the authoritative excerpt from the immutable transcript.
        claim.source_excerpt = selected
        selected_numbers = _numeric_tokens(selected)
        for level in claim.levels:
            level_numbers = _numeric_tokens(level)
            if not level_numbers:
                raise ClaimEvidenceError(f"Claim {index} contains a non-numeric price level")
            if _NON_PRICE_LEVEL_RE.search(level):
                raise ClaimEvidenceError(f"Claim {index} contains a duration or percentage as a price level")
            if not level_numbers <= selected_numbers:
                raise ClaimEvidenceError(
                    f"Claim {index} contains a numeric level not present in its cited evidence"
                )
        _apply_review_policy(claim, selected)
        if claim.scoreability == "not_scoreable" and not claim.not_scoreable_reason:
            raise ClaimEvidenceError(f"Claim {index} is not scoreable but has no reason")
        if claim.scoreability != "not_scoreable" and claim.claim_type == "not_scoreable":
            raise ClaimEvidenceError(f"Claim {index} has contradictory scoreability fields")
        if claim.scoreability == "conditional_scoreable" and not (claim.condition or "").strip():
            raise ClaimEvidenceError(f"Claim {index} is conditional but has no explicit condition")


def build_cache_key(video: dict, model: str, prompt_sha256: str, reasoning_effort: str = "low") -> str:
    return sha256_json({
        "schema_version": CLAIM_SCHEMA_VERSION,
        "evidence_policy": EVIDENCE_POLICY,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "prompt_sha256": prompt_sha256,
        "request_metadata": {
            "video_id": video["video_id"],
            "upload_date": video.get("upload_date"),
            "category": video.get("category"),
            "title": video.get("title"),
            "transcript_sha256": video["transcript_sha256"],
        },
    })


def validate_cached_artifact(
    artifact: dict,
    *,
    collection_id: str,
    video: dict,
    transcript: str,
    prompt_sha256: str,
    cache_key: str,
    model: str,
    reasoning_effort: str,
) -> None:
    expected = {
        "video_id": video["video_id"],
        "transcript_sha256": video["transcript_sha256"],
        "prompt_sha256": prompt_sha256,
        "cache_key": cache_key,
        "requested_model": model,
        "reasoning_effort": reasoning_effort,
        "schema_version": CLAIM_SCHEMA_VERSION,
        "evidence_policy": EVIDENCE_POLICY,
    }
    for key, value in expected.items():
        if artifact.get(key) != value:
            raise ClaimEvidenceError(f"Cached artifact has an unexpected {key}")
    raw_claims = artifact.get("claims", [])
    if not isinstance(raw_claims, list):
        raise ClaimEvidenceError("Cached artifact claims must be an array")
    fields = set(ClaimCandidate.model_fields)
    candidates = []
    for index, claim in enumerate(raw_claims, start=1):
        if not isinstance(claim, dict):
            raise ClaimEvidenceError("Cached artifact contains a non-object claim")
        expected_claim_fields = {
            "claim_id": f"{video['video_id']}-c{index:03d}",
            "video_id": video["video_id"],
            "upload_date": video.get("upload_date"),
            "category": video.get("category"),
            "source_transcript": video.get("transcript_txt"),
            "transcript_sha256": video["transcript_sha256"],
        }
        if any(claim.get(key) != value for key, value in expected_claim_fields.items()):
            raise ClaimEvidenceError("Cached artifact contains non-canonical claim identity metadata")
        candidates.append(
            ClaimCandidate.model_validate({key: value for key, value in claim.items() if key in fields})
        )
    parsed = ModelClaimExtraction(
        video_id=video["video_id"],
        claims=candidates,
        extraction_notes=artifact.get("extraction_notes", []),
    )
    validate_extraction(parsed, video["video_id"], transcript)
    application_fields = {
        "source_excerpt",
        "normalized_horizon_hours",
        "human_review_required",
        "review_required_fields",
        "review_flags",
        "scoreability",
        "not_scoreable_reason",
    }
    for raw, canonical in zip(raw_claims, parsed.claims, strict=True):
        canonical_payload = canonical.model_dump(mode="json")
        if any(raw.get(key) != canonical_payload.get(key) for key in application_fields):
            raise ClaimEvidenceError("Cached artifact does not contain canonical review/evidence fields")


def usage_payload(response: object) -> dict:
    usage = getattr(response, "usage", None)
    details = getattr(usage, "input_tokens_details", None) if usage else None
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "cached_input_tokens": int(getattr(details, "cached_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def estimate_claim_cost_usd(usage: dict, settings: Settings) -> float | None:
    input_rate = settings.openai_claim_input_usd_per_1m
    output_rate = settings.openai_claim_output_usd_per_1m
    if input_rate is None or output_rate is None:
        return None
    cached_rate = settings.openai_claim_cached_input_usd_per_1m
    if cached_rate is None:
        cached_rate = input_rate
    cached_tokens = min(usage["cached_input_tokens"], usage["input_tokens"])
    regular_tokens = usage["input_tokens"] - cached_tokens
    cost = (
        regular_tokens * input_rate
        + cached_tokens * cached_rate
        + usage["output_tokens"] * output_rate
    ) / 1_000_000
    return round(cost, 8)


def _request_input(video: dict, transcript: str) -> str:
    metadata = {
        "video_id": video["video_id"],
        "upload_date": video["upload_date"],
        "category": video["category"],
        "title": video["title"],
        "transcript_sha256": video["transcript_sha256"],
    }
    return (
        "VIDEO METADATA (authoritative JSON):\n"
        + json.dumps(metadata, ensure_ascii=False, indent=2)
        + "\n\nLINE-NUMBERED TRANSCRIPT (authoritative evidence):\n"
        + line_numbered_transcript(transcript)
    )


def _is_retriable(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError, ClaimEvidenceError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in {408, 409, 429} or exc.status_code >= 500
    return False


def _extract_one(
    *,
    client: OpenAI,
    settings: Settings,
    collection_id: str,
    video: dict,
    transcript: str,
    prompt: str,
    prompt_sha256: str,
    cache_key: str,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[dict, int]:
    failed_attempts = 0
    log_path = settings.logs_dir / "claim_extraction.jsonl"
    for attempt in range(settings.openai_max_retries + 1):
        try:
            response = client.responses.parse(
                model=settings.openai_claim_model,
                instructions=prompt,
                input=_request_input(video, transcript),
                text_format=ModelClaimExtraction,
                reasoning={"effort": settings.openai_claim_reasoning_effort},
                store=False,
                metadata={
                    "project": "market-analysis-audit-lab",
                    "collection_id": collection_id,
                    "video_id": video["video_id"],
                    "schema_version": CLAIM_SCHEMA_VERSION,
                },
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                raise ClaimEvidenceError("The API response contained no parsed structured output")
            try:
                validate_extraction(parsed, video["video_id"], transcript)
            except ClaimEvidenceError as exc:
                quarantine_dir = settings.logs_dir / "claim_extraction_quarantine"
                write_json_atomic(quarantine_dir / f"{video['video_id']}__attempt-{attempt + 1}.json", {
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "video_id": video["video_id"],
                    "attempt": attempt + 1,
                    "error": str(exc),
                    "response_id": getattr(response, "id", None),
                    "parsed_output": parsed.model_dump(mode="json"),
                })
                raise
            usage = usage_payload(response)
            claims = []
            for index, candidate in enumerate(parsed.claims, start=1):
                claims.append({
                    "claim_id": f"{video['video_id']}-c{index:03d}",
                    "video_id": video["video_id"],
                    "upload_date": video["upload_date"],
                    "category": video["category"],
                    "source_transcript": video["transcript_txt"],
                    "transcript_sha256": video["transcript_sha256"],
                    **candidate.model_dump(mode="json"),
                })
            artifact = {
                "schema_version": CLAIM_SCHEMA_VERSION,
                "evidence_policy": EVIDENCE_POLICY,
                "collection_id": collection_id,
                "api_collection_id": collection_id,
                "cache_key": cache_key,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "video_id": video["video_id"],
                "upload_date": video["upload_date"],
                "category": video["category"],
                "title": video["title"],
                "source_transcript": video["transcript_txt"],
                "transcript_sha256": video["transcript_sha256"],
                "prompt_sha256": prompt_sha256,
                "requested_model": settings.openai_claim_model,
                "reasoning_effort": settings.openai_claim_reasoning_effort,
                "response_model": getattr(response, "model", settings.openai_claim_model),
                "response_id": getattr(response, "id", None),
                "usage": usage,
                "estimated_cost_usd": estimate_claim_cost_usd(usage, settings),
                "extraction_notes": parsed.extraction_notes,
                "claims": claims,
            }
            append_json_line(log_path, {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "event": "api_success",
                "video_id": video["video_id"],
                "response_id": artifact["response_id"],
                "attempt": attempt + 1,
                "usage": usage,
            })
            return artifact, failed_attempts
        except Exception as exc:
            failed_attempts += 1
            retriable = _is_retriable(exc) and attempt < settings.openai_max_retries
            append_json_line(log_path, {
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
    raise RuntimeError("Claim extraction retry loop ended unexpectedly")


def _load_collection_artifacts(
    settings: Settings,
    collection_id: str,
    expected_videos: list[dict],
    *,
    prompt_sha256: str | None = None,
) -> list[dict]:
    """Load at most one exact artifact for each manifest video, never directory-glob residue."""
    artifacts = []
    for video in expected_videos:
        path = settings.claims_dir / f"{video['video_id']}.claims.json"
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        if payload.get("collection_id") != collection_id or payload.get("video_id") != video["video_id"]:
            continue
        if payload.get("transcript_sha256") != video.get("transcript_sha256"):
            continue
        if prompt_sha256 is not None:
            transcript_path = settings.workspace_dir / video["transcript_txt"]
            if not transcript_path.is_file() or sha256_file(transcript_path) != video["transcript_sha256"]:
                continue
            transcript = transcript_path.read_text(encoding="utf-8")
            cache_key = build_cache_key(
                video,
                settings.openai_claim_model,
                prompt_sha256,
                settings.openai_claim_reasoning_effort,
            )
            try:
                validate_cached_artifact(
                    payload,
                    collection_id=collection_id,
                    video=video,
                    transcript=transcript,
                    prompt_sha256=prompt_sha256,
                    cache_key=cache_key,
                    model=settings.openai_claim_model,
                    reasoning_effort=settings.openai_claim_reasoning_effort,
                )
            except (ClaimEvidenceError, ValueError, TypeError):
                continue
        artifacts.append(payload)
    return artifacts


def run_claim_extraction(
    settings: Settings,
    *,
    limit: int | None = None,
    video_ids: list[str] | None = None,
    force: bool = False,
    client: OpenAI | None = None,
) -> Path:
    manifest_path = settings.pack_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Manifest not found. Run the manifest stage first.")
    manifest = read_json(manifest_path)
    collection_id = manifest.get("collection_id")
    if not collection_id:
        raise SystemExit("Manifest predates collection IDs. Rebuild the manifest first.")

    scope = set(settings.audit_scope_categories)
    eligible_videos = [
        video
        for video in manifest.get("videos", [])
        if video.get("transcript_txt") and video.get("category") in scope
    ]
    videos = eligible_videos
    eligible_ids = {video["video_id"] for video in eligible_videos}
    if len(eligible_ids) != len(eligible_videos):
        raise SystemExit("Manifest contains duplicate audit-eligible video IDs.")
    if video_ids:
        requested = set(video_ids)
        missing = sorted(requested - eligible_ids)
        if missing:
            raise SystemExit(f"Requested video IDs are not audit-eligible: {', '.join(missing)}")
        videos = [video for video in videos if video["video_id"] in requested]
    if limit is not None:
        if limit < 1:
            raise SystemExit("--limit must be at least 1")
        videos = videos[:limit]
    if not videos:
        raise SystemExit("No audit-eligible transcripts selected for extraction.")

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    prompt_sha256 = sha256_text(prompt)
    cache_root = settings.cache_dir / "claim_extraction"
    jobs = []
    for video in videos:
        transcript_path = settings.workspace_dir / video["transcript_txt"]
        if not transcript_path.exists() or sha256_file(transcript_path) != video["transcript_sha256"]:
            raise SystemExit(f"Transcript integrity check failed for {video['video_id']}")
        transcript = transcript_path.read_text(encoding="utf-8")
        cache_key = build_cache_key(
            video,
            settings.openai_claim_model,
            prompt_sha256,
            settings.openai_claim_reasoning_effort,
        )
        cache_path = cache_root / f"{video['video_id']}__{cache_key}.json"
        cached = None
        if not force and cache_path.exists():
            try:
                cached = read_json(cache_path)
            except (json.JSONDecodeError, OSError, TypeError):
                cached = None
        if cached:
            try:
                validate_cached_artifact(
                    cached,
                    collection_id=collection_id,
                    video=video,
                    transcript=transcript,
                    prompt_sha256=prompt_sha256,
                    cache_key=cache_key,
                    model=settings.openai_claim_model,
                    reasoning_effort=settings.openai_claim_reasoning_effort,
                )
            except (ClaimEvidenceError, ValueError, TypeError):
                cached = None
        if cached and cached.get("collection_id") != collection_id:
            original_collection_id = cached.get("api_collection_id") or cached.get("collection_id")
            cached = dict(cached)
            cached["api_collection_id"] = original_collection_id
            cached["reused_from_collection_id"] = cached.get("collection_id")
            cached["collection_id"] = collection_id
        if cached:
            cached = dict(cached)
            cached["estimated_cost_usd"] = estimate_claim_cost_usd(cached.get("usage", {}), settings)
        jobs.append({
            "video": video,
            "transcript": transcript,
            "cache_key": cache_key,
            "cache_path": cache_path,
            "cached": cached,
        })

    cache_misses = [job for job in jobs if job["cached"] is None]
    if cache_misses and client is None:
        settings.require_openai_configuration()
        client = OpenAI(
            api_key=settings.openai_api_key_value,
            max_retries=0,
            timeout=settings.openai_timeout_seconds,
        )

    settings.claims_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    cache_hits = 0
    successful_api_calls = 0
    failed_attempts = 0
    run_usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    run_costs: list[float | None] = []

    cache_miss_jobs = []
    for job in jobs:
        video = job["video"]
        if job["cached"] is not None:
            artifact = job["cached"]
            cache_hits += 1
            write_json_atomic(settings.claims_dir / f"{video['video_id']}.claims.json", artifact)
        else:
            cache_miss_jobs.append(job)

    extraction_errors = []
    if cache_miss_jobs:
        assert client is not None
        workers = min(settings.openai_concurrency, len(cache_miss_jobs))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="claim-extraction") as executor:
            futures = {
                executor.submit(
                    _extract_one,
                    client=client,
                    settings=settings,
                    collection_id=collection_id,
                    video=job["video"],
                    transcript=job["transcript"],
                    prompt=prompt,
                    prompt_sha256=prompt_sha256,
                    cache_key=job["cache_key"],
                ): job
                for job in cache_miss_jobs
            }
            for future in as_completed(futures):
                job = futures[future]
                video = job["video"]
                try:
                    artifact, video_failed_attempts = future.result()
                except Exception as exc:
                    extraction_errors.append({
                        "video_id": video["video_id"],
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    })
                    continue
                failed_attempts += video_failed_attempts
                successful_api_calls += 1
                for key in run_usage:
                    run_usage[key] += artifact["usage"][key]
                run_costs.append(artifact.get("estimated_cost_usd"))
                write_json_atomic(job["cache_path"], artifact)
                write_json_atomic(settings.claims_dir / f"{video['video_id']}.claims.json", artifact)

    artifacts = _load_collection_artifacts(
        settings,
        collection_id,
        eligible_videos,
        prompt_sha256=prompt_sha256,
    )
    all_claims = [claim for artifact in artifacts for claim in artifact.get("claims", [])]
    total_usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for artifact in artifacts:
        for key in total_usage:
            total_usage[key] += int(artifact.get("usage", {}).get(key, 0) or 0)
    jsonl = "".join(json.dumps(claim, ensure_ascii=False, separators=(",", ":")) + "\n" for claim in all_claims)
    write_text_atomic(settings.claims_dir / "claims.jsonl", jsonl)

    artifact_costs = [artifact.get("estimated_cost_usd") for artifact in artifacts]
    total_estimated_cost = None if any(value is None for value in artifact_costs) else round(sum(artifact_costs), 8)
    run_estimated_cost = None if any(value is None for value in run_costs) else round(sum(run_costs), 8)
    completed_video_ids = {artifact["video_id"] for artifact in artifacts}
    completed_count = len(completed_video_ids)
    review_flag_counts = Counter(
        flag
        for claim in all_claims
        for flag in claim.get("review_flags", [])
    )
    summary = {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "evidence_policy": EVIDENCE_POLICY,
        "extraction_run_id": f"extract-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{sha256_json(sorted(completed_video_ids))[:8]}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if completed_count == len(eligible_ids) else "partial",
        "collection_id": collection_id,
        "model": settings.openai_claim_model,
        "reasoning_effort": settings.openai_claim_reasoning_effort,
        "audit_scope_categories": list(settings.audit_scope_categories),
        "prompt_sha256": prompt_sha256,
        "eligible_videos": len(eligible_ids),
        "selected_videos_this_run": len(jobs),
        "completed_videos": completed_count,
        "cache_hits_this_run": cache_hits,
        "successful_api_calls_this_run": successful_api_calls,
        "failed_or_retried_calls_this_run": failed_attempts,
        "failed_videos_this_run": extraction_errors,
        "concurrency": settings.openai_concurrency,
        "api_calls_this_run": successful_api_calls + failed_attempts,
        "usage_this_run": run_usage,
        "usage_all_artifacts": total_usage,
        "api_response_artifacts": sum(bool(artifact.get("response_id")) for artifact in artifacts),
        "estimated_cost_usd_this_run": run_estimated_cost,
        "estimated_cost_usd_all_artifacts": total_estimated_cost,
        "pricing_configured": total_estimated_cost is not None,
        "cost_scope": "accepted response artifacts only; failed attempts are not included because the API response did not expose usage",
        "total_claims": len(all_claims),
        "scoreable_claims": sum(claim["scoreability"] == "scoreable" for claim in all_claims),
        "conditional_claims": sum(claim["scoreability"] == "conditional_scoreable" for claim in all_claims),
        "not_scoreable_claims": sum(claim["scoreability"] == "not_scoreable" for claim in all_claims),
        "human_review_required_claims": sum(
            claim.get("human_review_required") is True for claim in all_claims
        ),
        "review_flag_counts": dict(sorted(review_flag_counts.items())),
    }
    out = settings.claims_dir / "extraction_run.json"
    write_json_atomic(out, summary)
    if extraction_errors:
        raise SystemExit(
            f"Claim extraction failed for {len(extraction_errors)} video(s); "
            f"successful artifacts were cached. Re-run to retry failures."
        )
    return out
