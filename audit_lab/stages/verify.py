from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from audit_lab.settings import Settings
from audit_lab.utils.hash import sha256_file


def _workspace_path(settings: Settings, value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    return settings.workspace_dir / path.name


def verify_audit_pack(settings: Settings) -> dict:
    hashes_path = settings.pack_dir / "file_hashes.csv"
    pack_hashes_path = settings.pack_dir / "pack_hashes.json"
    run_summary_path = settings.pack_dir / "run_summary.json"
    required = [hashes_path, pack_hashes_path, run_summary_path]
    missing_required = [str(path) for path in required if not path.exists()]
    if missing_required:
        return {
            "status": "not_available",
            "verified": False,
            "missing_required_files": missing_required,
            "file_hash_count": 0,
        }

    with hashes_path.open(encoding="utf-8-sig", newline="") as f:
        hash_rows = list(csv.DictReader(f))

    failed_file_hashes = []
    for row in hash_rows:
        path = settings.workspace_dir / row["relative_path"]
        if (
            not path.exists()
            or path.stat().st_size != int(row["size_bytes"])
            or sha256_file(path) != row["sha256"]
        ):
            failed_file_hashes.append(row["relative_path"])

    pack_hashes = json.loads(pack_hashes_path.read_text(encoding="utf-8"))
    pack_targets = {
        "manifest_json_sha256": settings.pack_dir / "manifest.json",
        "manifest_csv_sha256": settings.pack_dir / "manifest.csv",
        "file_hashes_csv_sha256": hashes_path,
        "collection_validation_report_sha256": settings.pack_dir / "reports" / "collection_validation_report.md",
    }
    failed_pack_hashes = [
        key for key, path in pack_targets.items()
        if not path.exists() or sha256_file(path) != pack_hashes.get(key)
    ]

    run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
    zip_path = _workspace_path(settings, run_summary.get("zip_path", ""))
    zip_exists = zip_path.exists()
    zip_sha256_matches = zip_exists and sha256_file(zip_path) == run_summary.get("zip_sha256")
    zip_first_bad_member = None
    if zip_exists:
        try:
            with zipfile.ZipFile(zip_path) as archive:
                zip_first_bad_member = archive.testzip()
        except zipfile.BadZipFile:
            zip_first_bad_member = "<invalid-zip>"

    verified = not any([
        failed_file_hashes,
        failed_pack_hashes,
        not zip_sha256_matches,
        zip_first_bad_member,
    ])
    return {
        "status": "verified" if verified else "failed",
        "verified": verified,
        "file_hash_count": len(hash_rows),
        "failed_file_hash_count": len(failed_file_hashes),
        "failed_file_hashes": failed_file_hashes[:20],
        "failed_pack_hashes": failed_pack_hashes,
        "zip_path": str(zip_path),
        "zip_sha256": run_summary.get("zip_sha256"),
        "zip_sha256_matches": zip_sha256_matches,
        "zip_first_bad_member": zip_first_bad_member,
    }
