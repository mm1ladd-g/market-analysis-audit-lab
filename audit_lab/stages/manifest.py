from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from audit_lab.settings import Settings
from audit_lab.stages.classify import guess_category, load_category_config
from audit_lab.utils.hash import sha256_file, sha256_json
from audit_lab.utils.text import canonicalize_subtitle, normalize_text, safe_slug
from audit_lab.utils.validation import category_id, video_id as validate_video_id, youtube_watch_url


MAX_SUBTITLE_BYTES = 20 * 1024 * 1024


def compact_to_iso(date_compact: str | None) -> str | None:
    if date_compact and re.fullmatch(r"\d{8}", date_compact):
        return f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]}"
    return None


def published_at_utc(info: dict, upload_date: str | None) -> str | None:
    timestamp = info.get("release_timestamp") or info.get("timestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    if upload_date:
        return f"{upload_date}T12:00:00+00:00"
    return None


def in_date_range(upload_date_raw: str | None, settings: Settings) -> bool:
    if not upload_date_raw or not re.fullmatch(r"\d{8}", upload_date_raw):
        return False
    return settings.start_compact <= upload_date_raw <= settings.end_compact


def related_files_for_video(info_path: Path) -> list[Path]:
    stem = info_path.name.replace(".info.json", "")
    prefix = stem + "."
    return sorted(
        path for path in info_path.parent.iterdir()
        if path.is_file() and path.name.startswith(prefix)
    )


def pick_subtitle_file(files: list[Path], languages: tuple[str, ...] = ("en",)) -> Path | None:
    candidates = [
        p for p in files
        if p.name.lower().endswith((".srt", ".vtt")) or ".provided." in p.name.lower() and p.name.lower().endswith(".txt")
    ]
    if not candidates:
        return None

    def score(path: Path) -> int:
        name = path.name.lower()
        value = 0
        for index, language in enumerate(languages):
            if f".{language.casefold()}." in name:
                value += (len(languages) - index) * 100
                break
        if name.endswith(".srt"):
            value += 20
        return value

    return sorted(candidates, key=score, reverse=True)[0]


def subtitle_track_metadata(
    info: dict, subtitle_file: Path | None, languages: tuple[str, ...] = ("en",)
) -> tuple[str | None, str | None]:
    if subtitle_file is None:
        return None, None
    name = subtitle_file.name.lower()
    language = None
    for candidate in languages:
        if f".{candidate.lower()}." in name:
            language = candidate
            break
    if ".ai." in name:
        return language, "openai_audio_transcription"
    if ".provided." in name:
        return language, "operator_provided_transcript"
    manual_tracks = set((info.get("subtitles") or {}).keys())
    if language in manual_tracks:
        provenance = "youtube_manual_subtitle"
    else:
        provenance = "youtube_automatic_caption"
    return language, provenance


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_manifest(settings: Settings) -> Path:
    if not settings.raw_dir.exists():
        raise SystemExit(f"Raw directory not found: {settings.raw_dir}")

    if settings.pack_dir.exists():
        shutil.rmtree(settings.pack_dir)
    settings.pack_dir.mkdir(parents=True, exist_ok=True)

    transcripts_dir = settings.pack_dir / "transcripts"
    metadata_dir = settings.pack_dir / "metadata"
    reports_dir = settings.pack_dir / "reports"
    for directory in [transcripts_dir, metadata_dir, reports_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    all_info_paths = sorted(settings.raw_dir.glob("*.info.json"))
    info_by_path: dict[Path, dict] = {}
    source_ids: dict[Path, str] = {}
    for path in all_info_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit(f"Source metadata must be a JSON object: {path.name}")
        try:
            source_ids[path] = validate_video_id(payload.get("id"))
        except ValueError as exc:
            raise SystemExit(f"Unsafe source metadata in {path.name}: {exc}") from exc
        info_by_path[path] = payload
    collected_info_paths = [
        path for path in all_info_paths
        if in_date_range(info_by_path[path].get("upload_date", ""), settings)
    ]
    outside_range_info_paths = [path for path in all_info_paths if path not in collected_info_paths]

    video_ids = [source_ids[path] for path in collected_info_paths]
    duplicate_video_ids = sorted({video_id for video_id in video_ids if video_ids.count(video_id) > 1})
    if duplicate_video_ids:
        raise SystemExit(f"Duplicate video IDs in collection: {', '.join(duplicate_video_ids)}")

    source_channel_mismatches = [
        {
            "video_id": source_ids[path],
            "source_channel_id": info_by_path[path].get("channel_id"),
            "expected_channel_id": settings.youtube_channel_id,
            "source_file": str(path.relative_to(settings.workspace_dir)),
        }
        for path in collected_info_paths
        if info_by_path[path].get("channel_id") != settings.youtube_channel_id
    ]
    if settings.strict_source_channel and source_channel_mismatches:
        raise SystemExit(
            f"Source channel validation failed for {len(source_channel_mismatches)} collected videos."
        )

    category_overrides, category_rules = load_category_config(settings.category_overrides_file)
    manifest = {
        "audit_name": f"{settings.project_name} - Collection Pack",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "collection_id": None,
        "source_snapshot_sha256": None,
        "channel": {
            "url": settings.youtube_channel_url,
            "id": settings.youtube_channel_id,
            "analyst_name": settings.analyst_name,
        },
        "date_range": {
            "start": str(settings.start_date),
            "end": str(settings.end_date),
        },
        "collection_rules": {
            "source_mode": settings.source_mode,
            "include_upload_date_from": str(settings.start_date),
            "include_upload_date_to": str(settings.end_date),
            "strict_date_filter_applied_in_manifest": True,
            "subtitles_requested": list(settings.subtitle_languages),
            "video_files_downloaded": False,
            "raw_video_download_skipped": True,
            "audio_transcription_fallback_enabled": settings.transcription_fallback,
            "raw_audio_retained": settings.retain_raw_audio,
        },
        "methodology_notes": [
            "This pack includes only videos uploaded inside the requested date range.",
            "The collector may scan the public YouTube uploads feed, but the manifest excludes any video outside the date range.",
            "Market-closed days are not counted as missing uploads if no video was published for that market.",
            "Final scoring must use falsifiable claims, not vague commentary.",
            "Non-triggered scenarios must be marked Not Triggered, not correct.",
            "Every included file is hashed with SHA-256 for later integrity verification.",
            "Canonical transcript line numbers retain a hashed SRT/VTT timing sidecar when timing is available.",
        ],
        "validation": {
            "raw_info_json_files_found": len(all_info_paths),
            "collected_info_json_files_in_range": len(collected_info_paths),
            "excluded_info_json_files_outside_date_range": len(outside_range_info_paths),
            "source_channel_mismatches": len(source_channel_mismatches),
            "duplicate_video_ids": len(duplicate_video_ids),
        },
        "videos": [],
        "excluded_videos": [],
    }

    csv_rows: list[dict] = []
    collected_by_date: dict[str, list] = defaultdict(list)
    included_by_date: dict[str, list] = defaultdict(list)
    included_raw_files: set[Path] = set()
    provided_manifest = settings.raw_dir / "provided_sources.manifest.json"
    if provided_manifest.is_file():
        included_raw_files.add(provided_manifest)

    for info_path in collected_info_paths:
        info = info_by_path[info_path]
        video_id = source_ids[info_path]
        title = normalize_text(info.get("title", ""))
        upload_date_raw = info.get("upload_date", "")
        upload_date = compact_to_iso(upload_date_raw)
        webpage_url = str(info.get("webpage_url") or "")
        if settings.source_mode == "youtube":
            try:
                webpage_url = youtube_watch_url(
                    webpage_url or f"https://www.youtube.com/watch?v={video_id}",
                    video_id,
                )
            except ValueError as exc:
                raise SystemExit(f"Invalid YouTube source URL for {video_id}: {exc}") from exc
        description = info.get("description", "") or ""
        duration = info.get("duration")
        category_value = str(info.get("audit_category") or "") or guess_category(
            video_id, title, description, video_overrides=category_overrides, keyword_rules=category_rules
        )
        try:
            category = category_id(category_value)
        except ValueError as exc:
            raise SystemExit(f"Invalid audit category for {video_id}: {exc}") from exc

        files = related_files_for_video(info_path)
        for p in files:
            if p.is_file():
                included_raw_files.add(p)
        subtitle_file = pick_subtitle_file(files, settings.subtitle_languages)
        subtitle_language, subtitle_provenance = subtitle_track_metadata(
            info, subtitle_file, settings.subtitle_languages
        )
        audit_eligible = bool(subtitle_file) or not settings.require_subtitles_for_audit
        exclusion_reason = None if audit_eligible else "missing_subtitle"

        transcript_path = None
        transcript_timing_path = None
        transcript_sha256 = None
        transcript_timing_sha256 = None
        subtitle_sha256 = None
        transcript_char_count = 0
        transcript_line_count = 0

        if subtitle_file and subtitle_file.exists():
            if subtitle_file.stat().st_size > MAX_SUBTITLE_BYTES:
                raise SystemExit(f"Subtitle exceeds the 20 MiB safety limit for {video_id}")
            clean_text, timing_rows = canonicalize_subtitle(
                subtitle_file.read_text(encoding="utf-8", errors="replace")
            )
            transcript_char_count = len(clean_text)
            transcript_line_count = len(clean_text.splitlines()) if clean_text else 0
            transcript_path = transcripts_dir / f"{upload_date}_{video_id}_{safe_slug(category)}.txt"
            transcript_path.write_text(clean_text, encoding="utf-8")
            transcript_sha256 = sha256_file(transcript_path)
            subtitle_sha256 = sha256_file(subtitle_file)
            transcript_timing_path = transcripts_dir / f"{upload_date}_{video_id}_{safe_slug(category)}.timing.json"
            write_json(transcript_timing_path, {
                "schema_version": "transcript-timing-v1",
                "video_id": video_id,
                "source_subtitle": str(subtitle_file.relative_to(settings.workspace_dir)),
                "source_subtitle_sha256": subtitle_sha256,
                "canonical_transcript": str(transcript_path.relative_to(settings.workspace_dir)),
                "canonical_transcript_sha256": transcript_sha256,
                "timed": any(row.get("start_seconds") is not None for row in timing_rows),
                "lines": timing_rows,
            })
            transcript_timing_sha256 = sha256_file(transcript_timing_path)
            if not clean_text:
                audit_eligible = False
                exclusion_reason = "empty_transcript"

        metadata_payload = {
            "video_id": video_id,
            "title": title,
            "upload_date": upload_date,
            "upload_date_raw": upload_date_raw,
            "published_at_utc": published_at_utc(info, upload_date),
            "published_at_source": (
                "operator_provided_timestamp"
                if info.get("provided_source")
                else "youtube_timestamp"
                if info.get("release_timestamp") or info.get("timestamp")
                else "date_noon_fallback"
            ),
            "webpage_url": webpage_url,
            "duration_seconds": duration,
            "category": category,
            "description": description,
            "source_channel_id": info.get("channel_id"),
            "source_info_json": str(info_path.relative_to(settings.workspace_dir)),
            "subtitle_file": str(subtitle_file.relative_to(settings.workspace_dir)) if subtitle_file else None,
            "subtitle_language": subtitle_language,
            "subtitle_provenance": subtitle_provenance,
            "subtitle_sha256": subtitle_sha256,
            "transcript_txt": str(transcript_path.relative_to(settings.workspace_dir)) if transcript_path else None,
            "transcript_sha256": transcript_sha256,
            "transcript_timing_file": (
                str(transcript_timing_path.relative_to(settings.workspace_dir))
                if transcript_timing_path else None
            ),
            "transcript_timing_sha256": transcript_timing_sha256,
            "transcript_char_count": transcript_char_count,
            "transcript_line_count": transcript_line_count,
            "audit_eligible": audit_eligible,
            "exclusion_reason": exclusion_reason,
        }
        metadata_out = metadata_dir / f"{upload_date}_{video_id}.metadata.json"
        write_json(metadata_out, metadata_payload)

        video_record = {
            **{k: metadata_payload[k] for k in [
                "video_id", "title", "upload_date", "upload_date_raw", "webpage_url",
                "published_at_utc", "published_at_source", "duration_seconds", "category", "subtitle_file", "subtitle_sha256",
                "subtitle_language", "subtitle_provenance",
                "transcript_txt", "transcript_sha256", "transcript_timing_file",
                "transcript_timing_sha256", "transcript_char_count", "transcript_line_count"
            ]},
            "has_subtitle": bool(subtitle_file),
            "metadata_file": str(metadata_out.relative_to(settings.workspace_dir)),
            "audit_eligible": audit_eligible,
            "exclusion_reason": exclusion_reason,
            "score_status": "pending_claim_extraction" if audit_eligible else "excluded",
        }
        collected_by_date[upload_date].append(video_record)
        if audit_eligible:
            manifest["videos"].append(video_record)
            included_by_date[upload_date].append(video_record)
        else:
            manifest["excluded_videos"].append(video_record)
        csv_rows.append({
            "upload_date": upload_date,
            "category": category,
            "title": title,
            "video_id": video_id,
            "url": webpage_url,
            "has_subtitle": bool(subtitle_file),
            "transcript_char_count": transcript_char_count,
            "transcript_line_count": transcript_line_count,
            "subtitle_file": video_record["subtitle_file"] or "",
            "transcript_txt": video_record["transcript_txt"] or "",
            "transcript_timing_file": video_record["transcript_timing_file"] or "",
            "duration_seconds": duration or "",
            "audit_eligible": audit_eligible,
            "exclusion_reason": exclusion_reason or "",
        })

    manifest["videos"].sort(key=lambda x: (x.get("upload_date") or "", x.get("category") or "", x.get("title") or ""))
    manifest["excluded_videos"].sort(
        key=lambda x: (x.get("upload_date") or "", x.get("category") or "", x.get("title") or "")
    )
    csv_rows.sort(key=lambda x: (x.get("upload_date") or "", x.get("category") or "", x.get("title") or ""))

    raw_hash_records = []
    for p in sorted(included_raw_files):
        raw_hash_records.append({
            "scope": "raw_collected_in_range",
            "relative_path": str(p.relative_to(settings.workspace_dir)),
            "size_bytes": p.stat().st_size,
            "sha256": sha256_file(p),
        })
    source_snapshot_sha256 = sha256_json(raw_hash_records)
    collection_fingerprint = sha256_json({
        "channel_id": settings.youtube_channel_id,
        "date_range": [str(settings.start_date), str(settings.end_date)],
        "source_snapshot_sha256": source_snapshot_sha256,
    })
    collection_id = f"audit-{settings.start_compact}-{settings.end_compact}-{collection_fingerprint[:12]}"
    manifest["collection_id"] = collection_id
    manifest["source_snapshot_sha256"] = source_snapshot_sha256

    collected_videos = manifest["videos"] + manifest["excluded_videos"]
    category_counts = Counter(v["category"] for v in manifest["videos"])
    collected_category_counts = Counter(v["category"] for v in collected_videos)
    date_counts = {date: len(items) for date, items in sorted(included_by_date.items())}
    collected_date_counts = {date: len(items) for date, items in sorted(collected_by_date.items())}
    outside_range = [
        v for v in collected_videos
        if not (str(settings.start_date) <= v["upload_date"] <= str(settings.end_date))
    ]
    unknown_category_count = sum(1 for v in collected_videos if v["category"] == "unknown")

    manifest["summary"] = {
        "total_videos_found": len(collected_videos),
        "total_videos_in_manifest": len(manifest["videos"]),
        "videos_included": len(manifest["videos"]),
        "videos_automatically_excluded": len(manifest["excluded_videos"]),
        "videos_manually_excluded": 0,
        "videos_with_subtitles": sum(1 for v in manifest["videos"] if v["has_subtitle"]),
        "videos_without_subtitles": sum(1 for v in manifest["videos"] if not v["has_subtitle"]),
        "missing_subtitles_found": sum(1 for v in collected_videos if not v["has_subtitle"]),
        "subtitle_provenance_counts": dict(Counter(
            v.get("subtitle_provenance") or "missing"
            for v in collected_videos
        )),
        "unknown_category_count": unknown_category_count,
        "category_counts": dict(category_counts),
        "collected_category_counts": dict(collected_category_counts),
        "date_counts": date_counts,
        "collected_date_counts": collected_date_counts,
        "outside_range_in_manifest": len(outside_range),
        "source_channel_mismatches": len(source_channel_mismatches),
        "duplicate_video_ids": len(duplicate_video_ids),
    }
    manifest["validation"]["audit_eligible_videos"] = len(manifest["videos"])
    manifest["validation"]["automatically_excluded_videos"] = len(manifest["excluded_videos"])

    if outside_range:
        raise SystemExit("ERROR: Manifest contains videos outside the requested date range.")

    manifest_path = settings.pack_dir / "manifest.json"
    write_json(manifest_path, manifest)

    csv_path = settings.pack_dir / "manifest.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "upload_date", "category", "title", "video_id", "url", "has_subtitle",
            "transcript_char_count", "transcript_line_count", "subtitle_file", "transcript_txt", "duration_seconds",
            "transcript_timing_file", "audit_eligible", "exclusion_reason"
        ])
        writer.writeheader()
        writer.writerows(csv_rows)

    file_hash_rows = list(raw_hash_records)
    for p in sorted(settings.pack_dir.rglob("*")):
        if p.is_file():
            file_hash_rows.append({
                "scope": "audit_pack_generated",
                "relative_path": str(p.relative_to(settings.workspace_dir)),
                "size_bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            })

    hashes_csv_path = settings.pack_dir / "file_hashes.csv"
    with hashes_csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["scope", "relative_path", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows(file_hash_rows)

    pack_hashes = {
        "manifest_json_sha256": sha256_file(manifest_path),
        "manifest_csv_sha256": sha256_file(csv_path),
        "file_hashes_csv_sha256": sha256_file(hashes_csv_path),
    }
    write_json(settings.pack_dir / "pack_hashes.json", pack_hashes)

    report = build_collection_report(settings, manifest, pack_hashes)
    report_path = settings.pack_dir / "reports" / "collection_validation_report.md"
    report_path.write_text(report, encoding="utf-8")
    pack_hashes["collection_validation_report_sha256"] = sha256_file(report_path)
    write_json(settings.pack_dir / "pack_hashes.json", pack_hashes)

    zip_path = settings.workspace_dir / f"audit_pack_{settings.start_date}_to_{settings.end_date}_{collection_id}.zip"
    if zip_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        zip_path = settings.workspace_dir / (
            f"audit_pack_{settings.start_date}_to_{settings.end_date}_{collection_id}_{timestamp}.zip"
        )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(settings.pack_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(settings.workspace_dir))
        for p in sorted(included_raw_files):
            z.write(p, p.relative_to(settings.workspace_dir))

    summary = {
        "collection_id": collection_id,
        "source_snapshot_sha256": source_snapshot_sha256,
        "zip_path": str(zip_path),
        "zip_sha256": sha256_file(zip_path),
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "summary": manifest["summary"],
        "pack_hashes": pack_hashes,
    }
    write_json(settings.pack_dir / "run_summary.json", summary)
    return zip_path


def build_collection_report(settings: Settings, manifest: dict, pack_hashes: dict) -> str:
    lines = [
        "# Collection Validation Report",
        "",
        f"Project: {settings.project_name}",
        f"Created at UTC: {manifest['created_at_utc']}",
        f"Collection ID: {manifest['collection_id']}",
        f"Channel ID: {settings.youtube_channel_id}",
        f"Date range: {settings.start_date} to {settings.end_date} inclusive",
        "",
        "## Validation",
        f"- Raw info.json files found: {manifest['validation']['raw_info_json_files_found']}",
        f"- Collected videos inside range: {manifest['validation']['collected_info_json_files_in_range']}",
        f"- Audit-eligible videos: {manifest['validation']['audit_eligible_videos']}",
        f"- Automatically excluded videos: {manifest['validation']['automatically_excluded_videos']}",
        f"- Manually excluded videos: {manifest['summary']['videos_manually_excluded']}",
        f"- Excluded files outside range: {manifest['validation']['excluded_info_json_files_outside_date_range']}",
        f"- Videos outside range in final manifest: {manifest['summary']['outside_range_in_manifest']}",
        f"- Videos with subtitles: {manifest['summary']['videos_with_subtitles']}",
        f"- Missing subtitles found: {manifest['summary']['missing_subtitles_found']}",
        f"- Unknown categories: {manifest['summary']['unknown_category_count']}",
        f"- Source channel mismatches: {manifest['summary']['source_channel_mismatches']}",
        f"- Duplicate video IDs: {manifest['summary']['duplicate_video_ids']}",
        "",
        "## Category counts",
    ]
    for key, value in sorted(manifest["summary"]["category_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Pack hashes"])
    for key, value in pack_hashes.items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"
