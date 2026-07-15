from __future__ import annotations

import shutil
import tarfile
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from scripts.build_public_release_assets import _validate_checkout, build_assets


ROOT = Path(__file__).resolve().parents[1]
HAS_GIT_CHECKOUT = (ROOT / ".git").is_dir() and shutil.which("git") is not None


class PublicReleaseAssetTests(unittest.TestCase):
    @unittest.skipUnless(HAS_GIT_CHECKOUT, "release archives require Git and a checkout")
    def test_builder_produces_deterministic_website_compatible_archives(self) -> None:
        import subprocess

        payload = subprocess.run(
            ["git", "show", "HEAD:pyproject.toml"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        version = str(tomllib.loads(payload.decode("utf-8"))["project"]["version"])
        tag = f"v{version}"
        source_stem = f"market-analysis-audit-lab-{tag}"
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = build_assets(
                tag=tag,
                source_ref="HEAD",
                output_dir=Path(first_dir),
                allow_dirty=True,
            )
            second = build_assets(
                tag=tag,
                source_ref="HEAD",
                output_dir=Path(second_dir),
                allow_dirty=True,
            )

            self.assertEqual(
                [path.name for path in first],
                [
                    f"{source_stem}-source.zip",
                    f"{source_stem}-source.tar.gz",
                    f"{source_stem}-bilingual-docs.zip",
                ],
            )
            self.assertEqual([path.read_bytes() for path in first], [path.read_bytes() for path in second])

            with zipfile.ZipFile(first[0]) as source_zip:
                zip_files = {
                    name: source_zip.read(name)
                    for name in source_zip.namelist()
                    if not name.endswith("/")
                }
            with tarfile.open(first[1], "r:gz") as source_tar:
                tar_files = {
                    member.name: source_tar.extractfile(member).read()
                    for member in source_tar.getmembers()
                    if member.isfile()
                }
            self.assertEqual(zip_files, tar_files)

            with zipfile.ZipFile(first[2]) as docs_zip:
                docs_names = set(docs_zip.namelist())
            prefix = f"{source_stem}-docs/"
            self.assertIn(f"{prefix}README.md", docs_names)
            self.assertIn(f"{prefix}README.fa.md", docs_names)
            self.assertIn(f"{prefix}docs/en/installation.md", docs_names)
            self.assertIn(f"{prefix}docs/fa/installation.md", docs_names)
            self.assertIn(f"{prefix}configs/assets.example.json", docs_names)
            self.assertFalse(any("audit_lab/" in name for name in docs_names))
            self.assertFalse(
                any(
                    PurePosixPath(name).suffix.casefold()
                    in {".pdf", ".mp4", ".mov", ".srt", ".vtt", ".png", ".jpg", ".webp"}
                    for name in docs_names
                )
            )

    def test_builder_rejects_a_tag_that_does_not_match_project_version(self) -> None:
        if not HAS_GIT_CHECKOUT:
            self.skipTest("release archives require Git and a checkout")
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(ValueError, "does not match project version"):
                build_assets(
                    tag="v9.9.9",
                    source_ref="HEAD",
                    output_dir=Path(output_dir),
                    allow_dirty=True,
                )

    def test_builder_rejects_dirty_or_mismatched_checkout(self) -> None:
        commit = "a" * 40
        with patch("scripts.build_public_release_assets._git") as git:
            git.side_effect = lambda *args: commit if args[0] == "rev-parse" else " M pyproject.toml"
            with self.assertRaisesRegex(RuntimeError, "dirty working tree"):
                _validate_checkout(commit, allow_dirty=False)

        with patch("scripts.build_public_release_assets._git", return_value="b" * 40):
            with self.assertRaisesRegex(RuntimeError, "checked-out HEAD"):
                _validate_checkout(commit, allow_dirty=False)

    def test_release_workflow_excludes_checksum_manifest_from_its_own_inventory(self) -> None:
        workflow_path = ROOT / ".github/workflows/release.yml"
        if not workflow_path.is_file():
            self.skipTest("release workflow is repository-only metadata")
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn('checksum_file="market-analysis-audit-lab-${GITHUB_REF_NAME}-SHA256SUMS.txt"', workflow)
        self.assertIn('! -name "$checksum_file"', workflow)
        self.assertIn("subject-path: dist/*", workflow)


if __name__ == "__main__":
    unittest.main()
