from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from audit_lab.settings import Settings
from audit_lab.stages.extract_claims import (
    CLAIM_SCHEMA_VERSION,
    EVIDENCE_POLICY,
    PROMPT_PATH as CLAIM_PROMPT_PATH,
    REVIEW_REQUIRED_FIELDS,
    build_cache_key,
    validate_cached_artifact,
)
from audit_lab.stages.finalize import finalize_audit, verify_final_audit
from audit_lab.stages.manifest import build_manifest
from audit_lab.stages.report import write_dashboard_data
from audit_lab.stages.score_claims import (
    PROMPT_PATH as SCORING_PROMPT_PATH,
    SCORING_POLICY,
    SCORING_SCHEMA_VERSION,
    scoring_input_fingerprint,
    validate_score_artifact,
)
from audit_lab.stages.verify import verify_audit_pack
from audit_lab.utils.hash import sha256_file, sha256_json, sha256_text
from audit_lab.utils.jsonio import write_json_atomic, write_text_atomic


DEMO_NOTICE = (
    "SYNTHETIC DEMO: every identity, channel, transcript, price, claim, and result "
    "in this workspace is fictional and is not evidence about a real person or market event."
)
DEMO_VIDEO_IDS = {"DEMO_VIDEO_001", "DEMO_VIDEO_002"}
DEMO_RAW_FILES = {
    "20240103__DEMO_VIDEO_001.description",
    "20240103__DEMO_VIDEO_001.en.srt",
    "20240103__DEMO_VIDEO_001.info.json",
    "20240104__DEMO_VIDEO_002.description",
    "20240104__DEMO_VIDEO_002.en.srt",
    "20240104__DEMO_VIDEO_002.info.json",
}
DEMO_TOP_LEVEL_NAMES = {
    ".gitkeep", "SYNTHETIC_DEMO.txt", "analysis", "audit_pack", "final_audit",
    "final_audit_summary.json", "logs", "market-data", "raw", "reports", "review",
}


def synthetic_demo_settings(workspace: Path) -> Settings:
    """Return a complete, environment-independent configuration for the demo."""
    return Settings(
        _env_file=None,
        PROJECT_NAME="Market Analysis Audit Lab · Synthetic Demo",
        ANALYST_NAME="Synthetic Research Presenter (fictional)",
        SOURCE_MODE="provided",
        PROVIDED_SOURCES_DIR=workspace / "synthetic-import-not-used",
        YOUTUBE_CHANNEL_URL="https://example.invalid/synthetic-channel",
        YOUTUBE_CHANNEL_ID="UC_SYNTHETIC_DEMO_NOT_REAL",
        START_DATE="2024-01-01",
        END_DATE="2024-01-07",
        MAX_AUDIT_DAYS=120,
        WORKSPACE_DIR=workspace,
        SOURCE_RIGHTS_ACKNOWLEDGED=True,
        SUBTITLE_LANGUAGES="en",
        COLLECT_THUMBNAILS=False,
        TRANSCRIPTION_FALLBACK=False,
        RETAIN_RAW_AUDIO=False,
        REQUIRE_SUBTITLES_FOR_AUDIT=True,
        STRICT_SOURCE_CHANNEL=True,
        MAX_SCAN_ITEMS=220,
        AUDIT_SCOPE_CATEGORIES="crypto,global_markets",
        CATEGORY_OVERRIDES_FILE=None,
        ASSET_MAP_FILE=None,
        PRICE_OUTCOME_ONLY=True,
        INTERNATIONAL_MARKET_PROVIDER="yfinance",
        MARKET_CSV_DIR=None,
        AUDIT_MODE="offline",
        OPENAI_API_KEY=None,
        OPENAI_MODEL_CLAIM_EXTRACTION="synthetic-offline-fixture",
        OPENAI_MODEL_SCORING="synthetic-offline-fixture",
        OPENAI_CLAIM_REASONING_EFFORT="low",
        OPENAI_SCORING_REASONING_EFFORT="low",
        OPENAI_MAX_RETRIES=2,
        OPENAI_CONCURRENCY=3,
        OPENAI_TIMEOUT_SECONDS=180,
        OPENAI_CLAIM_INPUT_USD_PER_1M=None,
        OPENAI_CLAIM_CACHED_INPUT_USD_PER_1M=None,
        OPENAI_CLAIM_OUTPUT_USD_PER_1M=None,
        OPENAI_SCORING_INPUT_USD_PER_1M=None,
        OPENAI_SCORING_CACHED_INPUT_USD_PER_1M=None,
        OPENAI_SCORING_OUTPUT_USD_PER_1M=None,
        API_COST_ACKNOWLEDGED=False,
        OPENAI_TRANSCRIPTION_MODEL="whisper-1",
        TRANSCRIPTION_LANGUAGE=None,
        TRANSCRIPTION_PROMPT=None,
        TRANSCRIPTION_CHUNK_SECONDS=1200,
        PUBLICATION_MODE="private",
        PUBLIC_CLAIM_LEDGER=False,
        REPORT_DEFAULT_LANGUAGE="en",
    )


def _validate_demo_workspace_for_reset(workspace: Path) -> None:
    marker = workspace / "SYNTHETIC_DEMO.txt"
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != DEMO_NOTICE:
        raise RuntimeError("Refusing to replace a workspace without the exact synthetic-demo marker.")
    if any(path.is_symlink() for path in workspace.rglob("*")):
        raise RuntimeError("Refusing to replace a synthetic-demo workspace containing symbolic links.")
    unexpected_top = []
    for child in workspace.iterdir():
        name = child.name
        generated_zip = (
            name.startswith("audit_pack_2024-01-01_to_2024-01-07_audit-")
            or name.startswith("complete_audit_audit-20240101-20240107-")
        ) and name.endswith(".zip")
        if name not in DEMO_TOP_LEVEL_NAMES and not generated_zip:
            unexpected_top.append(name)
    if unexpected_top:
        raise RuntimeError(
            "Refusing to replace a synthetic-demo workspace with unexpected top-level artifacts: "
            + ", ".join(sorted(unexpected_top))
        )
    raw_dir = workspace / "raw"
    if not raw_dir.is_dir() or {path.name for path in raw_dir.iterdir()} != DEMO_RAW_FILES:
        raise RuntimeError("Refusing to replace a demo workspace whose raw source ledger is not the known fixture.")
    for path in raw_dir.glob("*.info.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("id") not in DEMO_VIDEO_IDS or payload.get("channel_id") != "UC_SYNTHETIC_DEMO_NOT_REAL":
            raise RuntimeError("Refusing to replace a demo workspace containing non-demo source metadata.")
    reports_dir = workspace / "reports"
    if reports_dir.exists():
        unexpected_reports = {
            path.name for path in reports_dir.iterdir()
            if path.name not in {"dashboard_data.json", "audit-report.pdf"}
        }
        if unexpected_reports:
            raise RuntimeError("Refusing to replace a demo workspace containing unknown report artifacts.")
    for protected in (workspace / "review", workspace / "market-data"):
        if protected.is_dir() and any(protected.iterdir()):
            raise RuntimeError(f"Refusing to replace a demo workspace containing data in {protected.name}/.")


def _info(video_id: str, upload_date: str, timestamp: int, title: str, category_hint: str) -> dict:
    return {
        "id": video_id,
        "title": title,
        "upload_date": upload_date,
        "timestamp": timestamp,
        "webpage_url": f"https://example.invalid/synthetic-video/{video_id}",
        "duration": 480,
        "channel_id": "UC_SYNTHETIC_DEMO_NOT_REAL",
        "channel": "Synthetic Research Presenter",
        "description": f"{DEMO_NOTICE} {category_hint}",
        "subtitles": {"en": [{"name": "Synthetic English captions"}]},
        "automatic_captions": {},
    }


def _write_source_fixture(settings: Settings) -> None:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    fixtures = [
        (
            "DEMO_VIDEO_001",
            "20240103",
            1704283200,
            "Synthetic Bitcoin scenario map — demo only",
            "bitcoin crypto",
            """1\n00:00:00,000 --> 00:00:04,000\nSynthetic demo transcript. This is not a real analyst.\n\n2\n00:00:04,000 --> 00:00:10,000\nBitcoin is above 100; while that level holds, the scenario expects 106.\n\n3\n00:00:10,000 --> 00:00:16,000\nIf price closes below 95, the bearish alternative targets 90.\n""",
        ),
        (
            "DEMO_VIDEO_002",
            "20240104",
            1704369600,
            "Synthetic gold levels — demo only",
            "gold xauusd global market",
            """1\n00:00:00,000 --> 00:00:04,000\nSynthetic demo transcript. No real person or event is represented.\n\n2\n00:00:04,000 --> 00:00:11,000\nGold holding 2000 keeps a move toward 2025 possible during the next day.\n""",
        ),
    ]
    for video_id, upload_date, timestamp, title, hint, subtitle in fixtures:
        base = f"{upload_date}__{video_id}"
        write_json_atomic(settings.raw_dir / f"{base}.info.json", _info(video_id, upload_date, timestamp, title, hint))
        write_text_atomic(settings.raw_dir / f"{base}.en.srt", subtitle)
        write_text_atomic(settings.raw_dir / f"{base}.description", DEMO_NOTICE + "\n")
    write_text_atomic(settings.workspace_dir / "SYNTHETIC_DEMO.txt", DEMO_NOTICE + "\n")


def _claim(video: dict, index: int, **values) -> dict:
    return {
        "claim_id": f"{video['video_id']}-c{index:03d}",
        "video_id": video["video_id"],
        "upload_date": video["upload_date"],
        "category": video["category"],
        "source_transcript": video["transcript_txt"],
        "transcript_sha256": video["transcript_sha256"],
        **values,
    }


def _seed_analysis(settings: Settings) -> None:
    manifest = json.loads((settings.pack_dir / "manifest.json").read_text(encoding="utf-8"))
    videos = {video["video_id"]: video for video in manifest["videos"]}
    btc = videos["DEMO_VIDEO_001"]
    gold = videos["DEMO_VIDEO_002"]
    claims = [
        _claim(
            btc, 1,
            claim_text="BTC holding 100 supports a move toward 106.",
            claim_type="scenario", source_excerpt="Bitcoin is above 100; while that level holds, the scenario expects 106.",
            source_line_start=2, source_line_end=2, assets=["BTC-USD"], levels=["100", "106"],
            direction="bullish", condition="Price holds above 100", invalidation_condition="Close below 100",
            time_horizon="next 24 hours", normalized_horizon_hours=24,
            scoreability="conditional_scoreable", not_scoreable_reason=None,
            extraction_confidence=0.99, human_review_required=True,
            review_required_fields=list(REVIEW_REQUIRED_FIELDS),
            review_flags=["ai_semantic_interpretation"],
        ),
        _claim(
            btc, 2,
            claim_text="A close below 95 would activate a bearish move toward 90.",
            claim_type="scenario", source_excerpt="If price closes below 95, the bearish alternative targets 90.",
            source_line_start=3, source_line_end=3, assets=["BTC-USD"], levels=["95", "90"],
            direction="bearish", condition="Price closes below 95", invalidation_condition=None,
            time_horizon="next 24 hours", normalized_horizon_hours=24,
            scoreability="conditional_scoreable", not_scoreable_reason=None,
            extraction_confidence=0.99, human_review_required=True,
            review_required_fields=list(REVIEW_REQUIRED_FIELDS),
            review_flags=["ai_semantic_interpretation"],
        ),
        _claim(
            gold, 1,
            claim_text="Gold holding 2000 keeps 2025 possible during the next day.",
            claim_type="scenario", source_excerpt="Gold holding 2000 keeps a move toward 2025 possible during the next day.",
            source_line_start=2, source_line_end=2, assets=["XAUUSD"], levels=["2000", "2025"],
            direction="bullish", condition="Gold holds 2000", invalidation_condition="Break below 2000",
            time_horizon="next 24 hours", normalized_horizon_hours=24,
            scoreability="conditional_scoreable", not_scoreable_reason=None,
            extraction_confidence=0.99, human_review_required=True,
            review_required_fields=list(REVIEW_REQUIRED_FIELDS),
            review_flags=["ai_semantic_interpretation"],
        ),
    ]
    by_video: dict[str, list[dict]] = {video_id: [] for video_id in videos}
    for claim in claims:
        by_video[claim["video_id"]].append(claim)
    settings.claims_dir.mkdir(parents=True, exist_ok=True)
    claim_prompt_sha256 = sha256_text(CLAIM_PROMPT_PATH.read_text(encoding="utf-8"))
    for video_id, rows in by_video.items():
        video = videos[video_id]
        transcript = (settings.workspace_dir / video["transcript_txt"]).read_text(encoding="utf-8")
        cache_key = build_cache_key(
            video,
            settings.openai_claim_model,
            claim_prompt_sha256,
            settings.openai_claim_reasoning_effort,
        )
        artifact = {
            "schema_version": CLAIM_SCHEMA_VERSION,
            "evidence_policy": EVIDENCE_POLICY,
            "collection_id": manifest["collection_id"],
            "cache_key": cache_key,
            "created_at_utc": "2024-01-08T00:00:00+00:00",
            "video_id": video_id,
            "upload_date": video["upload_date"],
            "category": video["category"],
            "title": video["title"],
            "source_transcript": video["transcript_txt"],
            "transcript_sha256": video["transcript_sha256"],
            "prompt_sha256": claim_prompt_sha256,
            "requested_model": settings.openai_claim_model,
            "reasoning_effort": settings.openai_claim_reasoning_effort,
            "response_model": None,
            "response_id": None,
            "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "estimated_cost_usd": 0.0,
            "extraction_notes": [DEMO_NOTICE],
            "claims": rows,
            "synthetic_demo": True,
        }
        validate_cached_artifact(
            artifact,
            collection_id=manifest["collection_id"],
            video=video,
            transcript=transcript,
            prompt_sha256=claim_prompt_sha256,
            cache_key=cache_key,
            model=settings.openai_claim_model,
            reasoning_effort=settings.openai_claim_reasoning_effort,
        )
        write_json_atomic(settings.claims_dir / f"{video_id}.claims.json", artifact)
    write_text_atomic(
        settings.claims_dir / "claims.jsonl",
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in claims),
    )
    write_json_atomic(settings.claims_dir / "extraction_run.json", {
        "schema_version": CLAIM_SCHEMA_VERSION, "evidence_policy": EVIDENCE_POLICY,
        "status": "complete",
        "collection_id": manifest["collection_id"], "model": "synthetic-offline-fixture",
        "reasoning_effort": settings.openai_claim_reasoning_effort,
        "audit_scope_categories": list(settings.audit_scope_categories),
        "prompt_sha256": claim_prompt_sha256, "eligible_videos": 2,
        "completed_videos": 2, "total_claims": 3, "scoreable_claims": 0,
        "conditional_claims": 3, "not_scoreable_claims": 0,
        "human_review_required_claims": 3,
        "review_flag_counts": {"ai_semantic_interpretation": 3},
        "usage_all_artifacts": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "synthetic_demo": True, "notice": DEMO_NOTICE,
    })

    outcome_rows = []
    prices = {
        claims[0]["claim_id"]: (101.0, 107.0, 100.0, 106.0),
        claims[1]["claim_id"]: (101.0, 107.0, 100.0, 106.0),
        claims[2]["claim_id"]: (2004.0, 2020.0, 2001.0, 2014.0),
    }
    market_fixture_path = settings.outcomes_dir / "market_data" / "synthetic-demo-hourly.json"
    fixture_series = {}
    for asset, anchor, summary in (
        ("BTC-USD", datetime.fromisoformat(btc["published_at_utc"]), prices[claims[0]["claim_id"]]),
        ("XAUUSD", datetime.fromisoformat(gold["published_at_utc"]), prices[claims[2]["claim_id"]]),
    ):
        opening, highest, lowest, close = summary
        bars = []
        for index in range(24):
            interpolated = opening + (close - opening) * index / 23
            bars.append({
                "timestamp_utc": (
                    anchor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=index)
                ).isoformat(),
                "open": round(interpolated, 6),
                "high": round(max(interpolated, highest if index == 12 else interpolated), 6),
                "low": round(min(interpolated, lowest if index == 1 else interpolated), 6),
                "close": round(close if index == 23 else interpolated, 6),
            })
        fixture_series[asset] = {
            "interval": "1h", "timestamp_semantics": "bar_open", "rows": bars,
        }
    write_json_atomic(market_fixture_path, {
        "schema_version": "synthetic-market-fixture-v1",
        "notice": DEMO_NOTICE,
        "series": fixture_series,
    })
    market_fixture_relative = str(market_fixture_path.relative_to(settings.workspace_dir))
    market_fixture_sha256 = sha256_file(market_fixture_path)
    for claim in claims:
        opening, high, low, close = prices[claim["claim_id"]]
        outcome_rows.append({
            "claim_id": claim["claim_id"], "video_id": claim["video_id"], "category": claim["category"],
            "published_at_utc": videos[claim["video_id"]]["published_at_utc"],
            "published_at_source": "synthetic_fixture", "status": "evaluated_for_price_outcome",
            "assets": [{
                "asset": claim["assets"][0], "series_key": claim["assets"][0],
                "provider": "Synthetic deterministic fixture", "venue": "No real venue", "symbol": claim["assets"][0],
                "interval": "1h", "proxy_note": DEMO_NOTICE, "status": "available",
                "source_file": market_fixture_relative, "source_sha256": market_fixture_sha256,
                "window_24h": {
                    "hours": 24, "status": "complete", "complete": True, "bar_count": 24,
                    "open": opening, "high": high, "low": low, "close": close,
                    "return_pct": round((close / opening - 1) * 100, 6),
                    "max_up_pct": round((high / opening - 1) * 100, 6),
                    "max_down_pct": round((low / opening - 1) * 100, 6),
                    "level_events": [],
                },
                "window_48h": {"hours": 48, "status": "not_requested_in_fixture", "complete": False},
            }],
        })
    public_series = {
        asset: {
            "status": "available", "provider": "Synthetic deterministic fixture",
            "venue": "No real venue", "symbol": asset, "interval": "1h", "timezone": "UTC",
            "timestamp_semantics": "bar_open", "source_file": market_fixture_relative,
            "source_sha256": market_fixture_sha256, "row_count": len(payload["rows"]),
        }
        for asset, payload in fixture_series.items()
    }
    outcomes = {
        "schema_version": "2.0.0", "collection_id": manifest["collection_id"],
        "created_at_utc": "2024-01-08T00:00:00+00:00", "audit_scope_categories": list(settings.audit_scope_categories),
        "price_outcome_only": True, "provider": "Synthetic deterministic fixture", "providers": [{
            "name": "Synthetic deterministic fixture", "scope": "Demo only", "resolution": "1 hour", "integrity": DEMO_NOTICE,
        }], "series": public_series, "claims": outcome_rows, "synthetic_demo": True, "notice": DEMO_NOTICE,
    }
    outcomes["market_evidence_snapshot_sha256"] = sha256_json({
        "collection_id": manifest["collection_id"],
        "scope": outcomes["audit_scope_categories"],
        "series": public_series,
        "claims": outcome_rows,
    })
    outcomes["outcome_snapshot_sha256"] = sha256_json(outcomes)
    write_json_atomic(settings.outcomes_dir / "claim_outcomes.json", outcomes)

    score_specs = {
        claims[0]["claim_id"]: ("correct", 1.0, True, "triggered"),
        claims[1]["claim_id"]: ("not_triggered", 0.0, False, "not_triggered"),
        claims[2]["claim_id"]: ("partially_correct", 0.5, True, "triggered"),
    }
    scores = []
    for claim in claims:
        result, score, counted, trigger = score_specs[claim["claim_id"]]
        scores.append({
            "claim_id": claim["claim_id"], "video_id": claim["video_id"], "upload_date": claim["upload_date"],
            "category": claim["category"], "result": result, "score": score,
            "counts_in_final_score": counted, "trigger_status": trigger, "data_sufficiency": "sufficient",
            "evidence_summary": "Synthetic values support this deterministic demonstration result.",
            "reasoning": DEMO_NOTICE, "evaluation_window": "24h",
            "scoring_confidence": 1.0,
        })
    settings.scores_dir.mkdir(parents=True, exist_ok=True)
    scoring_prompt_sha256 = sha256_text(SCORING_PROMPT_PATH.read_text(encoding="utf-8"))
    outcomes_by_claim = {row["claim_id"]: row for row in outcome_rows}
    for video_id, video in videos.items():
        video_claims = by_video[video_id]
        video_outcomes = [outcomes_by_claim[claim["claim_id"]] for claim in video_claims]
        rows = [score for score in scores if score["video_id"] == video_id]
        fingerprint = scoring_input_fingerprint(
            settings=settings,
            prompt_sha256=scoring_prompt_sha256,
            video=video,
            claims=video_claims,
            outcomes=video_outcomes,
        )
        artifact = {
            "schema_version": SCORING_SCHEMA_VERSION, "scoring_policy": SCORING_POLICY,
            "collection_id": manifest["collection_id"], "cache_key": fingerprint,
            "scoring_input_fingerprint": fingerprint,
            "created_at_utc": "2024-01-08T00:00:00+00:00", "video_id": video_id,
            "upload_date": video["upload_date"], "category": video["category"], "title": video["title"],
            "requested_model": settings.openai_scoring_model,
            "reasoning_effort": settings.openai_scoring_reasoning_effort,
            "prompt_sha256": scoring_prompt_sha256,
            "response_model": None, "response_id": None,
            "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "estimated_cost_usd": 0.0, "scoring_notes": [DEMO_NOTICE], "scores": rows,
            "synthetic_demo": True,
        }
        validate_score_artifact(artifact, video, video_claims, outcomes_by_claim)
        write_json_atomic(settings.scores_dir / f"{video_id}.scores.json", artifact)
    write_text_atomic(
        settings.scores_dir / "scores.jsonl",
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in scores),
    )
    write_json_atomic(settings.scores_dir / "scoring_run.json", {
        "schema_version": SCORING_SCHEMA_VERSION, "scoring_policy": SCORING_POLICY,
        "status": "complete",
        "collection_id": manifest["collection_id"], "model": "synthetic-offline-fixture",
        "audit_scope_categories": list(settings.audit_scope_categories),
        "price_outcome_only": settings.price_outcome_only,
        "prompt_sha256": scoring_prompt_sha256, "eligible_videos": 2,
        "completed_videos": 2, "total_claims": 3, "counted_claims": 2, "final_score": 75.0,
        "results": {"correct": 1, "partially_correct": 1, "not_triggered": 1},
        "category_breakdown": {
            "crypto": {"total_claims": 2, "counted_claims": 1, "score": 100.0, "results": {"correct": 1, "not_triggered": 1}},
            "global_markets": {"total_claims": 1, "counted_claims": 1, "score": 50.0, "results": {"partially_correct": 1}},
        },
        "usage_all_artifacts": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "synthetic_demo": True, "notice": DEMO_NOTICE,
    })


def seed_synthetic_demo(workspace: Path) -> dict:
    workspace = workspace.resolve()
    if workspace.exists():
        existing = [child for child in workspace.iterdir() if child.name != ".gitkeep"]
        substantive = [
            child
            for child in existing
            if child.is_symlink() or child.is_file() or (child.is_dir() and any(child.iterdir()))
        ]
        marker = workspace / "SYNTHETIC_DEMO.txt"
        if substantive and not marker.is_file():
            raise RuntimeError(
                "Refusing to replace a non-demo workspace. Choose an empty directory or remove "
                "the existing audit artifacts yourself after reviewing them."
            )
        if substantive:
            _validate_demo_workspace_for_reset(workspace)
        for child in workspace.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    workspace.mkdir(parents=True, exist_ok=True)
    settings = synthetic_demo_settings(workspace)
    _write_source_fixture(settings)
    build_manifest(settings)
    _seed_analysis(settings)
    write_dashboard_data(settings)
    final_zip = finalize_audit(settings)
    pack_check = verify_audit_pack(settings)
    final_check = verify_final_audit(settings)
    return {
        "synthetic_demo": True,
        "notice": DEMO_NOTICE,
        "workspace": str(workspace),
        "collection_verified": pack_check.get("verified"),
        "final_verified": final_check.get("verified"),
        "final_zip": str(final_zip),
    }
