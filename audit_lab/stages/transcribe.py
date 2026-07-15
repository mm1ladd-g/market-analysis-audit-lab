from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from audit_lab.settings import Settings
from audit_lab.stages.classify import guess_category, load_category_config
from audit_lab.stages.manifest import pick_subtitle_file, related_files_for_video
from audit_lab.utils.hash import sha256_file, sha256_json, sha256_text
from audit_lab.utils.jsonio import read_json, write_json_atomic, write_text_atomic
from audit_lab.utils.validation import (
    category_id,
    sanitized_subprocess_env,
    video_id as validate_video_id,
    youtube_watch_url,
)


TRANSCRIPTION_SCHEMA_VERSION = "timed-transcription-v1"
MAX_API_FILE_BYTES = 24 * 1024 * 1024
MAX_AUDIO_FILE_BYTES = 512 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 6 * 60 * 60
MEDIA_PROBE_TIMEOUT_SECONDS = 30
MEDIA_DOWNLOAD_TIMEOUT_SECONDS = 45 * 60
MEDIA_TRANSCODE_TIMEOUT_SECONDS = 60 * 60


def _timestamp_srt(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0) or 0)
        end = max(float(segment.get("end", start) or start), start + 0.001)
        blocks.append(f"{index}\n{_timestamp_srt(start)} --> {_timestamp_srt(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _segment_value(segment: Any, key: str, default: Any = None) -> Any:
    if isinstance(segment, dict):
        return segment.get(key, default)
    return getattr(segment, key, default)


def _response_segments(response: Any, *, offset: float, fallback_duration: float) -> list[dict]:
    raw_segments = getattr(response, "segments", None) or []
    rows = []
    for segment in raw_segments:
        start = float(_segment_value(segment, "start", 0) or 0) + offset
        end = float(_segment_value(segment, "end", start - offset) or start - offset) + offset
        rows.append({"start": start, "end": max(end, start + 0.001), "text": str(_segment_value(segment, "text", ""))})
    if rows:
        return rows
    text = str(getattr(response, "text", "") or "").strip()
    return [{"start": offset, "end": offset + max(fallback_duration, 0.001), "text": text}] if text else []


def _duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=MEDIA_PROBE_TIMEOUT_SECONDS,
        env=sanitized_subprocess_env(),
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe could not determine audio duration")
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_AUDIO_DURATION_SECONDS:
        raise RuntimeError("Audio duration is invalid or exceeds the six-hour safety limit")
    return duration


def _download_audio(info: dict, info_path: Path) -> Path:
    video_id = validate_video_id(info.get("id"))
    source_url = str(info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}")
    url = youtube_watch_url(source_url, video_id)
    output = info_path.with_name(info_path.name.replace(".info.json", ".audio.%(ext)s"))
    try:
        result = subprocess.run(
            [
                "yt-dlp", "--ignore-config", "--no-playlist", "--quiet", "--no-warnings",
                "--max-filesize", "512M", "--extract-audio", "--audio-format", "mp3",
                "--audio-quality", "64K", "--output", str(output), url,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
            env=sanitized_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Audio download exceeded the 45-minute safety limit") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed with exit code {result.returncode}")
    audio_prefix = info_path.name.replace(".info.json", ".audio.")
    candidates = sorted(
        path for path in info_path.parent.iterdir()
        if path.is_file() and path.name.startswith(audio_prefix)
    )
    if len(candidates) != 1:
        raise RuntimeError("Audio extraction did not produce exactly one file")
    if candidates[0].stat().st_size > MAX_AUDIO_FILE_BYTES:
        raise RuntimeError("Extracted audio exceeds the 512 MiB safety limit")
    return candidates[0]


def _chunks(audio: Path, chunk_seconds: int) -> list[tuple[Path, float, float]]:
    duration = _duration_seconds(audio)
    if audio.stat().st_size <= MAX_API_FILE_BYTES:
        return [(audio, 0.0, duration)]
    chunk_dir = audio.parent / f".{audio.stem}-chunks"
    if chunk_dir.exists():
        if chunk_dir.is_symlink():
            chunk_dir.unlink()
        else:
            shutil.rmtree(chunk_dir)
    chunk_dir.mkdir()
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(audio), "-f", "segment",
                "-segment_time", str(chunk_seconds), "-reset_timestamps", "1",
                "-c:a", "libmp3lame", "-b:a", "64k", str(chunk_dir / "chunk-%03d.mp3"),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=MEDIA_TRANSCODE_TIMEOUT_SECONDS,
            env=sanitized_subprocess_env(),
        )
    except Exception:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise
    if result.returncode != 0:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise RuntimeError(f"ffmpeg chunking failed with exit code {result.returncode}")
    paths = sorted(chunk_dir.glob("chunk-*.mp3"))
    if not paths or any(path.stat().st_size > MAX_API_FILE_BYTES for path in paths):
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise RuntimeError("Audio chunks do not satisfy the API file-size boundary")
    return [
        (path, index * float(chunk_seconds), _duration_seconds(path))
        for index, path in enumerate(paths)
    ]


def run_transcription_fallback(settings: Settings, *, client: OpenAI | None = None) -> Path:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    summary_path = settings.logs_dir / "transcription_run.json"
    if not settings.transcription_fallback:
        write_json_atomic(summary_path, {
            "schema_version": TRANSCRIPTION_SCHEMA_VERSION,
            "status": "disabled",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "message": "TRANSCRIPTION_FALLBACK is false; no audio was downloaded or sent to an API.",
        })
        return summary_path
    if settings.source_mode != "youtube":
        raise SystemExit("Audio transcription fallback is available only with SOURCE_MODE=youtube.")
    settings.require_source_configuration()
    if settings.openai_transcription_model != "whisper-1":
        raise SystemExit(
            "The v0.1 timed-transcript adapter requires OPENAI_TRANSCRIPTION_MODEL=whisper-1 "
            "because it records segment timestamps."
        )
    category_overrides, category_rules = load_category_config(settings.category_overrides_file)
    scope = set(settings.audit_scope_categories)
    jobs = []
    outside_scope_skipped = 0
    for info_path in sorted(settings.raw_dir.glob("*.info.json")):
        info = json.loads(info_path.read_text(encoding="utf-8"))
        try:
            source_video_id = validate_video_id(info.get("id"))
        except ValueError as exc:
            raise SystemExit(f"Unsafe video ID in {info_path.name}: {exc}") from exc
        info["id"] = source_video_id
        upload_date = str(info.get("upload_date") or "")
        if not settings.start_compact <= upload_date <= settings.end_compact:
            continue
        if info.get("channel_id") != settings.youtube_channel_id:
            raise SystemExit(f"Source channel mismatch for {source_video_id}")
        category_value = str(info.get("audit_category") or "") or guess_category(
            source_video_id,
            str(info.get("title") or ""),
            str(info.get("description") or ""),
            video_overrides=category_overrides,
            keyword_rules=category_rules,
        )
        try:
            category = category_id(category_value)
        except ValueError as exc:
            raise SystemExit(f"Invalid audit category for {source_video_id}: {exc}") from exc
        if category not in scope:
            outside_scope_skipped += 1
            continue
        if pick_subtitle_file(related_files_for_video(info_path), settings.subtitle_languages):
            continue
        jobs.append((info_path, info))

    if not jobs:
        write_json_atomic(summary_path, {
            "schema_version": TRANSCRIPTION_SCHEMA_VERSION,
            "status": "complete",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": settings.openai_transcription_model,
            "videos_missing_captions": 0,
            "videos_transcribed": 0,
            "videos_failed": 0,
            "videos_outside_audit_scope_skipped": outside_scope_skipped,
            "message": "Every in-range video already has a selected caption track; no audio was downloaded.",
        })
        return summary_path
    settings.require_openai_configuration()
    if client is None:
        client = OpenAI(
            api_key=settings.openai_api_key_value,
            max_retries=settings.openai_max_retries,
            timeout=settings.openai_timeout_seconds,
        )

    results = []
    for info_path, info in jobs:
        audio: Path | None = None
        chunk_paths: list[Path] = []
        try:
            audio = _download_audio(info, info_path)
            audio_sha256 = sha256_file(audio)
            prompt_sha256 = sha256_text(settings.transcription_prompt or "")
            cache_key = sha256_json({
                "schema_version": TRANSCRIPTION_SCHEMA_VERSION,
                "model": settings.openai_transcription_model,
                "language": settings.transcription_language,
                "prompt_sha256": prompt_sha256,
                "audio_sha256": audio_sha256,
            })
            cache_path = settings.cache_dir / "transcription" / f"{info['id']}__{cache_key}.json"
            cached = read_json(cache_path) if cache_path.is_file() else None
            if cached:
                segments = cached["segments"]
                response_ids = cached.get("response_ids", [])
                cache_hit = True
            else:
                segments = []
                response_ids = []
                chunks = _chunks(audio, settings.transcription_chunk_seconds)
                chunk_paths = [path for path, _, _ in chunks if path != audio]
                for chunk_path, offset, duration in chunks:
                    request: dict[str, Any] = {
                        "model": settings.openai_transcription_model,
                        "response_format": "verbose_json",
                        "timestamp_granularities": ["segment"],
                    }
                    if settings.transcription_language:
                        request["language"] = settings.transcription_language
                    if settings.transcription_prompt:
                        request["prompt"] = settings.transcription_prompt
                    with chunk_path.open("rb") as handle:
                        response = client.audio.transcriptions.create(file=handle, **request)
                    response_ids.append(getattr(response, "id", None))
                    segments.extend(_response_segments(response, offset=offset, fallback_duration=duration))
                write_json_atomic(cache_path, {
                    "schema_version": TRANSCRIPTION_SCHEMA_VERSION,
                    "cache_key": cache_key,
                    "video_id": info["id"],
                    "model": settings.openai_transcription_model,
                    "audio_sha256": audio_sha256,
                    "prompt_sha256": prompt_sha256,
                    "language": settings.transcription_language,
                    "response_ids": response_ids,
                    "segments": segments,
                })
                cache_hit = False
            language = settings.transcription_language or "und"
            base = info_path.name.replace(".info.json", "")
            subtitle_path = info_path.with_name(f"{base}.ai.{language}.srt")
            segments_path = info_path.with_name(f"{base}.ai.segments.json")
            write_text_atomic(subtitle_path, segments_to_srt(segments))
            write_json_atomic(segments_path, {
                "schema_version": TRANSCRIPTION_SCHEMA_VERSION,
                "video_id": info["id"],
                "source_audio_sha256": audio_sha256,
                "model": settings.openai_transcription_model,
                "language": settings.transcription_language,
                "segments": segments,
            })
            results.append({
                "video_id": info["id"], "status": "complete", "cache_hit": cache_hit,
                "source_audio_sha256": audio_sha256, "subtitle_file": subtitle_path.name,
                "segments_file": segments_path.name, "segment_count": len(segments),
                "response_ids": response_ids,
            })
        except Exception as exc:
            results.append({"video_id": info.get("id"), "status": "failed", "error_type": type(exc).__name__})
        finally:
            if not settings.retain_raw_audio:
                for path in chunk_paths:
                    path.unlink(missing_ok=True)
                chunk_dirs = {path.parent for path in chunk_paths}
                for directory in chunk_dirs:
                    if directory.is_dir():
                        shutil.rmtree(directory)
                if audio is not None:
                    audio.unlink(missing_ok=True)

    failures = [item for item in results if item["status"] != "complete"]
    write_json_atomic(summary_path, {
        "schema_version": TRANSCRIPTION_SCHEMA_VERSION,
        "status": "complete" if not failures else "partial",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": settings.openai_transcription_model,
        "videos_missing_captions": len(jobs),
        "videos_transcribed": len(results) - len(failures),
        "videos_failed": len(failures),
        "videos_outside_audit_scope_skipped": outside_scope_skipped,
        "raw_audio_retained": settings.retain_raw_audio,
        "results": results,
    })
    if failures:
        raise SystemExit(f"Audio transcription failed for {len(failures)} video(s); inspect {summary_path}")
    return summary_path
