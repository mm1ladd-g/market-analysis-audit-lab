#!/usr/bin/env python3
"""Build deterministic, website-compatible public release archives."""

from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAG_PATTERN = re.compile(
    r"v(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\Z"
)
DOC_PATHS = (
    "ASSET_LICENSES.yml",
    "CHANGELOG.md",
    "CITATION.cff",
    "CODE_OF_CONDUCT.fa.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.fa.md",
    "CONTRIBUTING.md",
    "DCO",
    "GOVERNANCE.fa.md",
    "GOVERNANCE.md",
    "LICENSE",
    "NOTICE",
    "PRIVACY.fa.md",
    "PRIVACY.md",
    "README.fa.md",
    "README.md",
    "ROADMAP.md",
    "SECURITY.fa.md",
    "SECURITY.md",
    "SUPPORT.fa.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    "configs",
    "docs",
)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _project_version(source_commit: str) -> str:
    payload = _git("show", f"{source_commit}:pyproject.toml")
    return str(tomllib.loads(payload)["project"]["version"])


def _validate_checkout(source_commit: str, *, allow_dirty: bool) -> None:
    head_commit = _git("rev-parse", "HEAD^{commit}")
    if source_commit != head_commit:
        raise RuntimeError("source ref must resolve to the checked-out HEAD commit")
    if not allow_dirty:
        status = _git("status", "--porcelain=v1", "--untracked-files=all")
        if status:
            raise RuntimeError("refusing to build release assets from a dirty working tree")


def _archive(
    *,
    archive_format: str,
    prefix: str,
    output: Path,
    source_commit: str,
    paths: tuple[str, ...] = (),
) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to replace an existing release asset: {output}")
    command = [
        "archive",
        f"--format={archive_format}",
        f"--prefix={prefix}",
        f"--output={output}",
        source_commit,
    ]
    command.extend(paths)
    _git(*command)


def build_assets(
    *,
    tag: str,
    source_ref: str,
    output_dir: Path,
    allow_dirty: bool = False,
) -> list[Path]:
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError("tag must use the exact vMAJOR.MINOR.PATCH form")
    version = match.group("version")
    source_commit = _git("rev-parse", f"{source_ref}^{{commit}}")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RuntimeError("source ref did not resolve to a full commit hash")
    _validate_checkout(source_commit, allow_dirty=allow_dirty)
    project_version = _project_version(source_commit)
    if version != project_version:
        raise ValueError(f"tag {tag} does not match project version {project_version}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_stem = f"market-analysis-audit-lab-{tag}"
    source_prefix = f"{source_stem}/"
    docs_prefix = f"{source_stem}-docs/"
    outputs = [
        output_dir / f"{source_stem}-source.zip",
        output_dir / f"{source_stem}-source.tar.gz",
        output_dir / f"{source_stem}-bilingual-docs.zip",
    ]

    _archive(
        archive_format="zip",
        prefix=source_prefix,
        output=outputs[0],
        source_commit=source_commit,
    )
    _archive(
        archive_format="tar.gz",
        prefix=source_prefix,
        output=outputs[1],
        source_commit=source_commit,
    )
    _archive(
        archive_format="zip",
        prefix=docs_prefix,
        output=outputs[2],
        source_commit=source_commit,
        paths=DOC_PATHS,
    )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="release tag, for example v0.1.3")
    parser.add_argument("--source-ref", default="HEAD", help="Git commit or ref to archive")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        outputs = build_assets(tag=args.tag, source_ref=args.source_ref, output_dir=args.output_dir)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
