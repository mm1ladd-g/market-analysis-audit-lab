from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit


SAFE_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{3,64}")
SAFE_CATEGORY = re.compile(r"[a-z][a-z0-9_]{1,63}")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


def video_id(value: object) -> str:
    candidate = str(value or "")
    if not SAFE_VIDEO_ID.fullmatch(candidate):
        raise ValueError("Video ID must contain only 3-64 ASCII letters, digits, underscores, or hyphens")
    return candidate


def category_id(value: object) -> str:
    candidate = str(value or "")
    if not SAFE_CATEGORY.fullmatch(candidate):
        raise ValueError("Category must be a lowercase identifier containing 2-64 letters, digits, or underscores")
    return candidate


def youtube_channel_url(value: object) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in YOUTUBE_HOSTS:
        raise ValueError("YOUTUBE_CHANNEL_URL must be an HTTPS youtube.com channel URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("YOUTUBE_CHANNEL_URL must not contain credentials, a query, or a fragment")
    path = parsed.path.rstrip("/")
    if path.endswith("/videos"):
        path = path[:-7].rstrip("/")
    if path.startswith("/@"):
        identifier = path[2:]
    else:
        prefix = next((item for item in ("/channel/", "/c/", "/user/") if path.startswith(item)), None)
        identifier = path[len(prefix):] if prefix else ""
    if (
        not identifier
        or "/" in identifier
        or len(identifier) > 128
        or any(character.isspace() or ord(character) < 32 for character in identifier)
    ):
        raise ValueError("YOUTUBE_CHANNEL_URL does not identify a supported channel path")
    return f"https://www.youtube.com{path}"


def youtube_watch_url(value: object, expected_video_id: str) -> str:
    expected = video_id(expected_video_id)
    parsed = urlsplit(str(value or "").strip())
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Source webpage URL must not contain credentials or a fragment")
    host = (parsed.hostname or "").casefold()
    found = None
    if parsed.scheme == "https" and host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v", [])
            found = values[0] if len(values) == 1 else None
        elif parsed.path.startswith(("/shorts/", "/live/")):
            found = parsed.path.rstrip("/").split("/")[-1]
    elif parsed.scheme == "https" and host == "youtu.be":
        found = parsed.path.strip("/").split("/")[0]
    if found != expected:
        raise ValueError("Source webpage URL is not the expected HTTPS YouTube video")
    return f"https://www.youtube.com/watch?v={expected}"


def youtube_or_reserved_test_url(value: object, expected_video_id: str) -> str:
    """Validate a real YouTube URL or a non-routable ``.invalid`` demo URL."""
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").casefold()
    if host in YOUTUBE_HOSTS or host == "youtu.be":
        return youtube_watch_url(raw, expected_video_id)
    if (
        parsed.scheme != "https"
        or not host.endswith(".invalid")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(raw) > 2048
    ):
        raise ValueError("Source URL must be the expected YouTube video or a reserved .invalid demo URL")
    return urlunsplit(("https", host, parsed.path, "", ""))


def within(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("Resolved path leaves its allowed root")
    return resolved


def sanitized_subprocess_env() -> dict[str, str]:
    allowed = {
        "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.setdefault("PATH", os.defpath)
    environment.setdefault("HOME", "/tmp")
    return environment
