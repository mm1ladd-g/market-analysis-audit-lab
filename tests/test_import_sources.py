from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from audit_lab.settings import Settings
from audit_lab.stages.import_sources import import_provided_sources
from audit_lab.stages.manifest import build_manifest


class ProvidedSourceImportTests(unittest.TestCase):
    def test_authorized_plain_transcript_import_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "provided"
            source.mkdir()
            (source / "transcript.txt").write_text("Synthetic line one.\nSynthetic line two.\n", encoding="utf-8")
            (source / "sources.json").write_text(json.dumps({
                "channel_id": "UC_SYNTHETIC_TEST",
                "videos": [{
                    "video_id": "SYNTHETIC_001",
                    "title": "Synthetic Bitcoin example",
                    "upload_date": "2024-01-03",
                    "published_at_utc": "2024-01-03T12:34:56+00:00",
                    "category": "crypto",
                    "transcript_language": "en",
                    "transcript_path": "transcript.txt",
                }],
            }), encoding="utf-8")
            settings = Settings(
                _env_file=None,
                ANALYST_NAME="Synthetic Presenter",
                SOURCE_MODE="provided",
                PROVIDED_SOURCES_DIR=source,
                YOUTUBE_CHANNEL_ID="UC_SYNTHETIC_TEST",
                START_DATE="2024-01-01",
                END_DATE="2024-01-07",
                WORKSPACE_DIR=root / "workspace",
                SOURCE_RIGHTS_ACKNOWLEDGED=True,
            )
            import_provided_sources(settings)
            build_manifest(settings)
            manifest = json.loads((settings.pack_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["videos"]), 1)
            video = manifest["videos"][0]
            self.assertEqual(video["subtitle_provenance"], "operator_provided_transcript")
            self.assertEqual(video["published_at_source"], "operator_provided_timestamp")
            self.assertEqual(video["category"], "crypto")
            normalized = json.loads(
                (settings.raw_dir / "provided_sources.manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(normalized["schema_version"], "provided-source-ledger-v1")
            self.assertEqual(normalized["videos"][0]["video_id"], "SYNTHETIC_001")
            self.assertEqual(len(normalized["videos"][0]["transcript_sha256"]), 64)
            self.assertNotIn("transcript_path", normalized["videos"][0])

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "provided"
            source.mkdir()
            (root / "outside.txt").write_text("no", encoding="utf-8")
            (source / "sources.json").write_text(json.dumps({
                "channel_id": "UC_SYNTHETIC_TEST",
                "videos": [{
                    "video_id": "SYNTHETIC_001", "title": "Synthetic", "upload_date": "2024-01-03",
                    "published_at_utc": "2024-01-03T12:34:56+00:00", "transcript_path": "../outside.txt",
                }],
            }), encoding="utf-8")
            settings = Settings(
                _env_file=None, ANALYST_NAME="Synthetic Presenter", SOURCE_MODE="provided",
                PROVIDED_SOURCES_DIR=source, YOUTUBE_CHANNEL_ID="UC_SYNTHETIC_TEST",
                START_DATE="2024-01-01", END_DATE="2024-01-07", WORKSPACE_DIR=root / "workspace",
                SOURCE_RIGHTS_ACKNOWLEDGED=True,
            )
            with self.assertRaises(ValueError):
                import_provided_sources(settings)

    def test_non_youtube_webpage_url_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "provided"
            source.mkdir()
            (source / "transcript.txt").write_text("Synthetic transcript.\n", encoding="utf-8")
            (source / "sources.json").write_text(json.dumps({
                "channel_id": "UC_SYNTHETIC_TEST",
                "videos": [{
                    "video_id": "SYNTHETIC_001", "title": "Synthetic", "upload_date": "2024-01-03",
                    "published_at_utc": "2024-01-03T12:34:56+00:00",
                    "webpage_url": "https://attacker.example/watch?v=SYNTHETIC_001",
                    "transcript_path": "transcript.txt",
                }],
            }), encoding="utf-8")
            settings = Settings(
                _env_file=None, ANALYST_NAME="Synthetic Presenter", SOURCE_MODE="provided",
                PROVIDED_SOURCES_DIR=source, YOUTUBE_CHANNEL_ID="UC_SYNTHETIC_TEST",
                START_DATE="2024-01-01", END_DATE="2024-01-07", WORKSPACE_DIR=root / "workspace",
                SOURCE_RIGHTS_ACKNOWLEDGED=True,
            )
            with self.assertRaisesRegex(SystemExit, "Invalid YouTube webpage_url"):
                import_provided_sources(settings)


if __name__ == "__main__":
    unittest.main()
