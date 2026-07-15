#!/usr/bin/env python3
"""Generate a deterministic installed-package license inventory for a release."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
import sysconfig
from pathlib import Path


LICENSE_OVERRIDES = {
    "peewee": {
        "license": "MIT",
        "evidence": "https://github.com/coleifer/peewee/blob/master/LICENSE",
    },
}

LOCKED_REQUIREMENT = re.compile(
    r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;\\]+)"
)


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _locked_packages(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"dependency lock does not exist: {path}")
    packages: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOCKED_REQUIREMENT.match(line)
        if not match:
            continue
        name, version = match.groups()
        normalized = _normalized_name(name)
        prior = packages.setdefault(normalized, version)
        if prior != version:
            raise RuntimeError(
                f"dependency lock contains conflicting versions for {normalized}: {prior}, {version}"
            )
    if not packages:
        raise RuntimeError(f"dependency lock contains no pinned packages: {path}")
    return packages


def _license_value(distribution: importlib.metadata.Distribution) -> tuple[str | None, str]:
    name = (distribution.metadata.get("Name") or "").casefold()
    expression = (distribution.metadata.get("License-Expression") or "").strip()
    if expression:
        return expression, "License-Expression metadata"
    legacy = (distribution.metadata.get("License") or "").strip()
    if legacy and legacy.upper() not in {"UNKNOWN", "NONE"}:
        return legacy, "License metadata"
    classifiers = [
        value.removeprefix("License :: ")
        for value in distribution.metadata.get_all("Classifier", [])
        if value.startswith("License :: ")
    ]
    if classifiers:
        return "; ".join(sorted(classifiers)), "package classifier"
    override = LICENSE_OVERRIDES.get(name)
    if override:
        return override["license"], f"maintainer-reviewed override: {override['evidence']}"
    return None, "missing"


def _project_metadata(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"project metadata does not exist: {path}")
    try:
        import tomllib

        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        return {
            "name": project["name"],
            "version": project["version"],
            "license": project["license"],
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid project metadata in {path}: {exc}") from exc


def _project_urls(distribution: importlib.metadata.Distribution) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in distribution.metadata.get_all("Project-URL", []):
        label, separator, url = item.partition(",")
        if separator and label.strip() and url.strip():
            values[label.strip()] = url.strip()
    homepage = (distribution.metadata.get("Home-page") or "").strip()
    if homepage:
        values.setdefault("Homepage", homepage)
    return dict(sorted(values.items(), key=lambda item: item[0].casefold()))


def generate(output: Path, lock: Path, project_file: Path) -> dict:
    locked = _locked_packages(lock)
    packages = []
    failures = []
    installed: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name") or "<unnamed>"
        normalized = _normalized_name(name)
        if normalized in installed:
            failures.append(f"{name}: duplicate installed distribution name")
        installed[normalized] = distribution.version
        license_value, license_source = _license_value(distribution)
        license_files = sorted(
            str(path)
            for path in (distribution.files or [])
            if "license" in str(path).casefold() or "copying" in str(path).casefold()
        )
        if license_value is None:
            failures.append(f"{name}: no license metadata or reviewed override")
        if not license_files:
            failures.append(f"{name}: installed distribution contains no license/copying file")
        packages.append(
            {
                "name": name,
                "normalized_name": normalized,
                "version": distribution.version,
                "license": license_value or "NOASSERTION",
                "license_source": license_source,
                "license_files": license_files,
                "project_urls": _project_urls(distribution),
            }
        )
    for name, version in sorted(locked.items()):
        installed_version = installed.get(name)
        if installed_version is None:
            failures.append(f"{name}=={version}: locked package is not installed")
        elif installed_version != version:
            failures.append(
                f"{name}: lock requires {version}, installed distribution is {installed_version}"
            )
    for name, version in sorted(installed.items()):
        if name not in locked:
            failures.append(f"{name}=={version}: installed package is absent from the runtime lock")
    packages.sort(key=lambda item: (item["name"].casefold(), item["version"]))
    payload = {
        "schema_version": "1.0.0",
        "project": _project_metadata(project_file),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform_tag": sysconfig.get_platform(),
        "machine": platform.machine(),
        "requirements_lock": {
            "file": lock.name,
            "sha256": _sha256(lock),
            "package_count": len(locked),
        },
        "package_count": len(packages),
        "packages": packages,
    }
    if failures:
        raise RuntimeError("; ".join(failures))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path("requirements.lock"))
    parser.add_argument("--project-file", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args()
    try:
        payload = generate(args.output, args.lock, args.project_file)
    except RuntimeError as exc:
        print(f"Dependency-license inventory failed: {exc}", file=sys.stderr)
        return 1
    print(f"Recorded {payload['package_count']} installed packages in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
