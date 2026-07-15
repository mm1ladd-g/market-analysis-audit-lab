#!/usr/bin/env python3
"""Require a Developer Certificate of Origin sign-off on each reviewed commit."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


SIGN_OFF_VALUE = re.compile(
    r"(?P<name>[^\r\n<>]+?)\s+<(?P<email>[^<>@\s]+@[^<>@\s]+)>"
)


def _git(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def _identity(name: str, email: str) -> tuple[str, str]:
    return (" ".join(name.split()).casefold(), email.strip().casefold())


def _signoffs(message: str) -> set[tuple[str, str]]:
    trailers = _git("interpret-trailers", "--parse", input_text=message)
    identities: set[tuple[str, str]] = set()
    for line in trailers.splitlines():
        key, separator, value = line.partition(":")
        if not separator or key.casefold() != "signed-off-by":
            continue
        match = SIGN_OFF_VALUE.fullmatch(value.strip())
        if match:
            identities.add(_identity(match.group("name"), match.group("email")))
    return identities


def main() -> int:
    parser = argparse.ArgumentParser(description="Check DCO sign-offs in a commit range")
    parser.add_argument("base", help="base commit, excluded")
    parser.add_argument("head", help="head commit, included")
    args = parser.parse_args()

    try:
        commits = [
            value
            for value in _git("rev-list", "--reverse", "--no-merges", f"{args.base}..{args.head}").splitlines()
            if value
        ]
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"DCO check could not inspect the commit range: {exc}", file=sys.stderr)
        return 2

    missing = []
    try:
        for commit in commits:
            message = _git("show", "-s", "--format=%B", commit)
            author = _git("show", "-s", "--format=%an%x00%ae", commit).rstrip("\n").split("\0", 1)
            if len(author) != 2 or _identity(*author) not in _signoffs(message):
                subject = _git("show", "-s", "--format=%s", commit).strip()
                missing.append((commit[:12], subject))
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"DCO check could not inspect a commit: {exc}", file=sys.stderr)
        return 2

    if missing:
        print(
            "DCO check failed. Add an author-matching Signed-off-by trailer with `git commit -s`:",
            file=sys.stderr,
        )
        for commit, subject in missing:
            print(f"- {commit} {subject}", file=sys.stderr)
        return 1
    print(f"DCO check passed for {len(commits)} commit(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
