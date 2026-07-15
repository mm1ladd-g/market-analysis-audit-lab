from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from audit_lab.settings import Settings
from audit_lab.stages.collect import validate_existing_source_files
from audit_lab.utils.hash import sha256_file
from audit_lab.utils.jsonio import write_json_atomic, write_text_atomic
from audit_lab.utils.validation import (
    category_id,
    video_id as validate_video_id,
    youtube_or_reserved_test_url,
)


MAX_TRANSCRIPT_BYTES = 20 * 1024 * 1024
MAX_SOURCE_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_PROVIDED_VIDEOS = 5000


def _inside(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Transcript path escapes PROVIDED_SOURCES_DIR")
    return candidate


def import_provided_sources(settings: Settings) -> Path:
    """Normalize operator-provided metadata and transcripts into the raw ledger."""
    settings.require_source_configuration()
    source_root = settings.provided_sources_dir.resolve()
    manifest_path = source_root / "sources.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Provided-source manifest not found: {manifest_path}")
    if manifest_path.stat().st_size > MAX_SOURCE_MANIFEST_BYTES:
        raise SystemExit("Provided-source manifest exceeds the 5 MiB safety limit")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("sources.json must be a JSON object")
    if payload.get("channel_id") and str(payload["channel_id"]) != settings.youtube_channel_id:
        raise SystemExit("Provided-source channel ID does not match YOUTUBE_CHANNEL_ID")
    videos = payload.get("videos")
    if not isinstance(videos, list) or not videos or len(videos) > MAX_PROVIDED_VIDEOS:
        raise SystemExit("sources.json must contain 1-5000 video records")

    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    imported = []
    normalized_videos = []
    seen_ids: set[str] = set()
    for item in videos:
        if not isinstance(item, dict):
            raise SystemExit("Every sources.json video entry must be a JSON object")
        try:
            video_id = validate_video_id(item.get("video_id"))
        except ValueError as exc:
            raise SystemExit(f"Invalid provided video_id: {item.get('video_id')!r}") from exc
        if video_id in seen_ids:
            raise SystemExit(f"Duplicate provided video_id: {video_id}")
        seen_ids.add(video_id)
        try:
            upload_date = date.fromisoformat(str(item.get("upload_date")))
        except ValueError as exc:
            raise SystemExit(f"upload_date must be ISO YYYY-MM-DD for {video_id}") from exc
        if not settings.start_date <= upload_date <= settings.end_date:
            continue
        try:
            published = datetime.fromisoformat(str(item.get("published_at_utc")).replace("Z", "+00:00"))
        except ValueError as exc:
            raise SystemExit(f"published_at_utc must be an ISO timestamp for {video_id}") from exc
        if published.tzinfo is None:
            raise SystemExit(f"published_at_utc must include a timezone for {video_id}")
        published = published.astimezone(timezone.utc)
        transcript_source = _inside(source_root, str(item.get("transcript_path") or ""))
        if not transcript_source.is_file() or transcript_source.stat().st_size > MAX_TRANSCRIPT_BYTES:
            raise SystemExit(f"Transcript is missing or too large for {video_id}")
        suffix = transcript_source.suffix.casefold()
        if suffix not in {".txt", ".srt", ".vtt"}:
            raise SystemExit(f"Unsupported transcript extension for {video_id}: {suffix}")
        language = "".join(
            character if character.isascii() and (character.isalnum() or character in "_-") else "-"
            for character in str(item.get("transcript_language") or "und")
        ).strip("-")[:24] or "und"
        base = f"{upload_date.strftime('%Y%m%d')}__{video_id}"
        transcript_target = settings.raw_dir / f"{base}.provided.{language}{suffix}"
        shutil.copy2(transcript_source, transcript_target)
        category = item.get("category")
        if category not in (None, ""):
            try:
                category = category_id(category)
            except ValueError as exc:
                raise SystemExit(f"Invalid category for {video_id}: {exc}") from exc
        webpage_url = str(item.get("webpage_url") or "").strip()
        if webpage_url:
            try:
                webpage_url = youtube_or_reserved_test_url(webpage_url, video_id)
            except ValueError as exc:
                raise SystemExit(f"Invalid YouTube webpage_url for {video_id}: {exc}") from exc
        duration = item.get("duration_seconds")
        if duration is not None and (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not 0 < float(duration) <= 6 * 60 * 60
        ):
            raise SystemExit(f"duration_seconds must be between 0 and 21600 for {video_id}")
        title = str(item.get("title") or "Untitled provided source")[:1000]
        description = str(item.get("description") or "")[:200_000]
        info = {
            "id": video_id,
            "title": title,
            "upload_date": upload_date.strftime("%Y%m%d"),
            "timestamp": int(published.timestamp()),
            "webpage_url": webpage_url,
            "duration": duration,
            "channel_id": settings.youtube_channel_id,
            "channel": settings.analyst_name,
            "description": description,
            "audit_category": category,
            "provided_source": True,
            "provided_source_manifest": "provided_sources.manifest.json",
            "subtitles": {},
            "automatic_captions": {},
        }
        write_json_atomic(settings.raw_dir / f"{base}.info.json", info)
        write_text_atomic(settings.raw_dir / f"{base}.description", info["description"])
        imported.append({
            "video_id": video_id,
            "upload_date": upload_date.isoformat(),
            "published_at_utc": published.isoformat(),
            "transcript_file": transcript_target.name,
            "transcript_sha256": sha256_file(transcript_target),
        })
        normalized_videos.append({
            "video_id": video_id,
            "title": title,
            "upload_date": upload_date.isoformat(),
            "published_at_utc": published.isoformat(),
            "webpage_url": webpage_url,
            "duration_seconds": duration,
            "category": category,
            "transcript_language": language,
            "transcript_file": transcript_target.name,
            "transcript_sha256": sha256_file(transcript_target),
        })

    validate_existing_source_files(settings)
    if not imported:
        raise SystemExit("No provided sources fall inside the configured date range")
    normalized_manifest_path = settings.raw_dir / "provided_sources.manifest.json"
    write_json_atomic(normalized_manifest_path, {
        "schema_version": "provided-source-ledger-v1",
        "channel_id": settings.youtube_channel_id,
        "source_manifest_original_sha256": sha256_file(manifest_path),
        "date_range": {"start": str(settings.start_date), "end": str(settings.end_date)},
        "videos": normalized_videos,
    })
    summary_path = settings.logs_dir / "collection_run.json"
    write_json_atomic(summary_path, {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_mode": "provided",
        "channel_id": settings.youtube_channel_id,
        "date_range": {"start": str(settings.start_date), "end": str(settings.end_date)},
        "in_range_info_json_files": len(imported),
        "completeness_boundary_confirmed": True,
        "rights_acknowledged": settings.source_rights_acknowledged,
        "normalized_source_manifest": str(normalized_manifest_path.relative_to(settings.workspace_dir)),
        "normalized_source_manifest_sha256": sha256_file(normalized_manifest_path),
        "videos": imported,
    })
    return summary_path
