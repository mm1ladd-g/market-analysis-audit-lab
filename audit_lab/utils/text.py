from __future__ import annotations

import re
from typing import Any
from slugify import slugify


TIMESTAMP_LINE = re.compile(
    r"^\s*(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$"
)


def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace("\u200c", "‌")).strip()


def safe_slug(s: str, max_len: int = 180) -> str:
    out = slugify(s, allow_unicode=False, separator="_")
    out = re.sub(r"_+", "_", out).strip("_")
    return out[:max_len] or "item"


def _timestamp_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts
    return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)


def _clean_caption_line(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\{\\.*?\}", "", value)
    return normalize_text(value)


def canonicalize_subtitle(raw: str) -> tuple[str, list[dict[str, Any]]]:
    """Return canonical transcript text and a line-to-cue timing sidecar.

    SRT/VTT cue timing is retained without making timestamps part of the text
    sent to claim extraction. Plain-text transcripts receive explicit null
    timings, so downstream reviewers can distinguish timed and untimed input.
    """
    raw_lines = raw.lstrip("\ufeff").splitlines()
    has_timestamps = any(TIMESTAMP_LINE.match(line) for line in raw_lines)
    active_start: float | None = None
    active_end: float | None = None
    rows: list[dict[str, Any]] = []

    for line in raw_lines:
        line = line.strip()
        timestamp = TIMESTAMP_LINE.match(line)
        if timestamp:
            active_start = _timestamp_seconds(timestamp.group("start"))
            active_end = _timestamp_seconds(timestamp.group("end"))
            if active_end < active_start:
                active_end = active_start
            continue
        if not line:
            if has_timestamps:
                active_start = None
                active_end = None
            continue
        upper = line.upper()
        if upper.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if has_timestamps and active_start is None:
            continue
        cleaned = _clean_caption_line(line)
        if not cleaned:
            continue
        if rows and rows[-1]["text"] == cleaned:
            if has_timestamps and active_end is not None:
                rows[-1]["end_seconds"] = max(rows[-1]["end_seconds"], active_end)
            continue
        rows.append({
            "line": len(rows) + 1,
            "text": cleaned,
            "start_seconds": active_start if has_timestamps else None,
            "end_seconds": active_end if has_timestamps else None,
        })

    return "\n".join(row["text"] for row in rows).strip(), rows


def clean_subtitle_text(raw: str) -> str:
    return canonicalize_subtitle(raw)[0]
