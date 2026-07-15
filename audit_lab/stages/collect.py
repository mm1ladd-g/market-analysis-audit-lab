from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from rich.console import Console
from audit_lab.settings import Settings
from audit_lab.utils.jsonio import write_json_atomic
from audit_lab.utils.validation import (
    sanitized_subprocess_env,
    video_id as validate_video_id,
    youtube_channel_url,
)

console = Console()
COLLECTION_TIMEOUT_SECONDS = 4 * 60 * 60
MAX_COLLECTION_LOG_BYTES = 50 * 1024 * 1024


def validate_existing_source_files(settings: Settings) -> None:
    mismatches = []
    for path in sorted(settings.raw_dir.glob("*.info.json")):
        info = json.loads(path.read_text(encoding="utf-8"))
        try:
            source_video_id = validate_video_id(info.get("id"))
        except ValueError as exc:
            raise SystemExit(f"Unsafe video ID in {path.name}: {exc}") from exc
        if info.get("channel_id") != settings.youtube_channel_id:
            mismatches.append(f"{source_video_id}:{info.get('channel_id')}")
    if settings.strict_source_channel and mismatches:
        raise SystemExit(
            "Raw directory contains metadata from a different or unidentified channel: "
            + ", ".join(mismatches[:5])
        )


def summarize_collection_log(settings: Settings, log_text: str) -> dict:
    rejected_dates = re.findall(r"\[download\] (\d{4}-\d{2}-\d{2}) upload date is not in range", log_text)
    item_matches = re.findall(r"Downloading item (\d+) of (\d+)", log_text)
    scanned_items = int(item_matches[-1][0]) if item_matches else 0
    reported_playlist_items = int(item_matches[-1][1]) if item_matches else 0
    reached_before_start = any(value < str(settings.start_date) for value in rejected_dates)
    playlist_exhausted_before_limit = bool(item_matches) and reported_playlist_items < settings.max_scan_items
    return {
        "error_count": len(re.findall(r"^ERROR:", log_text, flags=re.MULTILINE)),
        "warning_count": len(re.findall(r"^WARNING:", log_text, flags=re.MULTILINE)),
        "scanned_items": scanned_items,
        "reported_playlist_items": reported_playlist_items,
        "rejected_newer_than_end": sum(value > str(settings.end_date) for value in rejected_dates),
        "rejected_older_than_start": sum(value < str(settings.start_date) for value in rejected_dates),
        "scan_reached_before_start": reached_before_start,
        "playlist_exhausted_before_limit": playlist_exhausted_before_limit,
        "completeness_boundary_confirmed": reached_before_start or playlist_exhausted_before_limit,
    }


def run_collection(settings: Settings) -> None:
    if settings.source_mode != "youtube":
        raise SystemExit("run_collection requires SOURCE_MODE=youtube; use the provided-source importer otherwise.")
    settings.require_source_configuration()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    validate_existing_source_files(settings)

    try:
        channel_url = youtube_channel_url(settings.youtube_channel_url)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    uploads_url = channel_url if channel_url.endswith("/videos") else channel_url + "/videos"
    log_path = settings.logs_dir / "yt-dlp_collect.log"

    cmd = [
        "yt-dlp",
        uploads_url,
        "--ignore-config",
        "--dateafter", settings.start_compact,
        "--datebefore", settings.end_compact,
        "--playlist-end", str(settings.max_scan_items),
        "--no-overwrites",
        "--js-runtimes", "deno",
        "--skip-download",
        "--write-info-json",
        "--write-description",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", ",".join(settings.subtitle_languages),
        "--sub-format", "srt/vtt/best",
        "--convert-subs", "srt",
        "--ignore-errors",
        "--no-write-playlist-metafiles",
        "--retries", "5",
        "--fragment-retries", "5",
        "--sleep-requests", "0.7",
        "--sleep-interval", "0.7",
        "--max-sleep-interval", "2",
        "-P", str(settings.raw_dir),
        "-o", "%(upload_date)s__%(id)s.%(ext)s",
    ]
    if settings.collect_thumbnails:
        cmd.insert(cmd.index("--write-subs"), "--write-thumbnail")

    header = f"""
Market Analysis Audit Lab - Collection Run
UTC: {datetime.now(timezone.utc).isoformat()}
Analyst: {settings.analyst_name}
Channel: {settings.youtube_channel_url}
Channel ID: {settings.youtube_channel_id}
Date range: {settings.start_date} to {settings.end_date} inclusive
Output: {settings.raw_dir}
Max scan items: {settings.max_scan_items}
""".strip()

    console.print(header)
    console.print("\nRunning yt-dlp...\n")

    with log_path.open("w", encoding="utf-8") as log:
        log.write(header + "\n\n")
        try:
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=COLLECTION_TIMEOUT_SECONDS,
                env=sanitized_subprocess_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise SystemExit(
                f"yt-dlp exceeded the {COLLECTION_TIMEOUT_SECONDS // 3600}-hour collection limit. "
                f"Review {log_path} and narrow the period or scan boundary."
            ) from exc
        code = result.returncode

    if code != 0:
        raise SystemExit(f"yt-dlp failed with exit code {code}. See {log_path}")

    validate_existing_source_files(settings)
    if log_path.stat().st_size > MAX_COLLECTION_LOG_BYTES:
        raise SystemExit(f"Collection log exceeded the 50 MiB safety limit: {log_path}")
    all_info_paths = sorted(settings.raw_dir.glob("*.info.json"))
    in_range_count = 0
    for path in all_info_paths:
        info = json.loads(path.read_text(encoding="utf-8"))
        upload_date = str(info.get("upload_date") or "")
        if settings.start_compact <= upload_date <= settings.end_compact:
            in_range_count += 1

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    log_summary = summarize_collection_log(settings, log_text)
    run_report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "channel_id": settings.youtube_channel_id,
        "date_range": {"start": str(settings.start_date), "end": str(settings.end_date)},
        "max_scan_items": settings.max_scan_items,
        "raw_info_json_files": len(all_info_paths),
        "in_range_info_json_files": in_range_count,
        **log_summary,
    }
    write_json_atomic(settings.logs_dir / "collection_run.json", run_report)

    if log_summary["error_count"]:
        raise SystemExit(f"Collection completed with logged errors. Review {log_path}")
    if not log_summary["completeness_boundary_confirmed"]:
        raise SystemExit(
            "Collection did not prove that scanning passed the start-date boundary. "
            "Increase MAX_SCAN_ITEMS and rerun."
        )
    if in_range_count == 0:
        raise SystemExit("Collection found no videos inside the configured date range.")

    console.print(f"\nCollection finished. In-range info.json files found: {in_range_count}")
    console.print(f"Completeness boundary confirmed: {log_summary['completeness_boundary_confirmed']}")
