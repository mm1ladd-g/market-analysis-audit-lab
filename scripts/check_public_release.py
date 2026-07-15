#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", "workspace", "tmp", "__pycache__"}
FORBIDDEN_TEXT = {
    "private subject name": re.compile(r"(?i)\b(?:" + "mo" + "na|ghav" + "ampour)\\b"),
    "private brand": re.compile(r"(?i)\b4" + "invest\\b"),
    "private deployment domain": re.compile(r"(?i)\b(?:audit\.)?mm1" + r"ladd\.me\b"),
    "host absolute path": re.compile(r"/Users/what" + "isi|/home/what" + "isi"),
    "OpenAI-looking secret": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "GitHub-looking secret": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    "Cloudflare-looking secret": re.compile(r"(?i)\beyJhIjoi[A-Za-z0-9_-]{20,}"),
    "private key material": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE" + r" KEY-----"),
    "bearer credential": re.compile(r"(?i)\bbearer\s+(?:eyJ|[A-Za-z0-9_-]{24,}\.)[A-Za-z0-9._-]{20,}"),
}
FORBIDDEN_SUFFIXES = {
    ".zip", ".tar", ".gz", ".mp4", ".mov", ".mp3", ".m4a", ".srt", ".vtt",
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
}
REQUIRED = {
    "LICENSE", "NOTICE", "README.md", "README.fa.md", "SECURITY.md", "SECURITY.fa.md",
    "PRIVACY.md", "PRIVACY.fa.md", "CONTRIBUTING.md", "CONTRIBUTING.fa.md",
    "CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT.fa.md", "GOVERNANCE.md", "GOVERNANCE.fa.md",
    "SUPPORT.md", "SUPPORT.fa.md", "THIRD_PARTY_NOTICES.md", "ASSET_LICENSES.yml",
    "CITATION.cff", "DCO", "CHANGELOG.md", "ROADMAP.md",
    ".env.example", ".gitignore", ".dockerignore", "Dockerfile", "docker-compose.yml",
}
REPOSITORY_REQUIRED = {
    ".github/workflows/ci.yml", ".github/workflows/codeql.yml",
    ".github/workflows/secret-scan.yml", ".github/workflows/dependency-review.yml",
    ".github/workflows/dco.yml", ".github/ISSUE_TEMPLATE/question.yml",
    ".github/workflows/release.yml",
}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def source_files() -> list[Path]:
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
        )
    except FileNotFoundError:
        tracked = None
    if tracked is not None and tracked.returncode == 0 and tracked.stdout:
        return [ROOT / value.decode() for value in tracked.stdout.split(b"\0") if value]
    return [
        path for path in ROOT.rglob("*")
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts)
    ]


def main() -> int:
    failures: list[str] = []
    files = source_files()
    relative = {str(path.relative_to(ROOT)) for path in files}
    for required in sorted(REQUIRED - relative):
        failures.append(f"missing required file: {required}")
    if (ROOT / ".git").exists() or (ROOT / ".github").exists():
        for required in sorted(REPOSITORY_REQUIRED - relative):
            failures.append(f"missing repository workflow: {required}")

    for path in files:
        rel = path.relative_to(ROOT)
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden generated/media artifact: {rel}")
        if path.name == ".env":
            failures.append(".env must never be tracked or packaged")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in FORBIDDEN_TEXT.items():
            if pattern.search(text):
                failures.append(f"{label}: {rel}")
        if path.suffix.casefold() == ".md":
            for raw_target in MARKDOWN_LINK.findall(text):
                target = raw_target.strip()
                if target.startswith("<") and ">" in target:
                    target = target[1:target.index(">")]
                else:
                    target = target.split(maxsplit=1)[0]
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith("#"):
                    continue
                clean_target = unquote(parsed.path)
                if not clean_target:
                    continue
                if clean_target.startswith("/"):
                    failures.append(f"absolute local Markdown link: {rel} -> {target}")
                    continue
                candidate = (path.parent / clean_target).resolve()
                try:
                    candidate.relative_to(ROOT.resolve())
                except ValueError:
                    failures.append(f"Markdown link leaves repository: {rel} -> {target}")
                    continue
                if not candidate.exists():
                    failures.append(f"broken local Markdown link: {rel} -> {target}")

    en = {path.name for path in (ROOT / "docs" / "en").glob("*.md")}
    fa = {path.name for path in (ROOT / "docs" / "fa").glob("*.md")}
    for name in sorted(en ^ fa):
        failures.append(f"documentation counterpart missing: {name}")
    for path in (ROOT / "docs" / "fa").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if '<div dir="rtl" lang="fa">' not in text:
            failures.append(f"Persian document lacks RTL wrapper: {path.relative_to(ROOT)}")

    if failures:
        print("PUBLIC RELEASE CHECK FAILED", file=sys.stderr)
        for failure in sorted(set(failures)):
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"Public release check passed: {len(files)} source files, no forbidden identity or secret patterns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
