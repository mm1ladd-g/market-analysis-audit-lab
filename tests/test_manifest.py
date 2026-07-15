from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from audit_lab.settings import Settings
from audit_lab.stages.manifest import build_manifest
from audit_lab.stages.verify import verify_audit_pack


class ManifestTests(unittest.TestCase):
    def make_settings(self, workspace: Path) -> Settings:
        return Settings(
            _env_file=None,
            WORKSPACE_DIR=workspace,
            YOUTUBE_CHANNEL_URL="https://youtube.com/@example",
            YOUTUBE_CHANNEL_ID="channel-1",
            START_DATE=date(2026, 6, 1),
            END_DATE=date(2026, 6, 1),
            PROJECT_NAME="Test Audit",
        )

    def write_info(self, raw: Path, video_id: str, title: str) -> Path:
        stem = f"20260601__{video_id}__{title}"
        path = raw / f"{stem}.info.json"
        path.write_text(json.dumps({
            "id": video_id,
            "title": title,
            "upload_date": "20260601",
            "channel_id": "channel-1",
            "webpage_url": f"https://youtube.com/watch?v={video_id}",
            "description": "",
            "duration": 600,
        }, ensure_ascii=False), encoding="utf-8")
        (raw / f"{stem}.description").write_text("", encoding="utf-8")
        return path

    def test_missing_subtitle_is_preserved_as_automatic_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            raw = workspace / "raw"
            raw.mkdir()
            first = self.write_info(raw, "video-a", "تحلیل بیت‌کوین")
            subtitle = first.with_name(first.name.replace(".info.json", ".fa-orig.srt"))
            subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\nبیتکوین بالا می‌رود\n", encoding="utf-8")
            self.write_info(raw, "video-b", "تحلیل بیت‌کوین دوم")

            settings = self.make_settings(workspace)
            zip_path = build_manifest(settings)
            manifest = json.loads((workspace / "audit_pack" / "manifest.json").read_text(encoding="utf-8"))

            self.assertTrue(zip_path.exists())
            self.assertEqual(manifest["summary"]["total_videos_found"], 2)
            self.assertEqual(manifest["summary"]["videos_included"], 1)
            self.assertEqual(manifest["summary"]["videos_automatically_excluded"], 1)
            self.assertEqual(manifest["summary"]["videos_manually_excluded"], 0)
            self.assertEqual(manifest["summary"]["missing_subtitles_found"], 1)
            self.assertEqual(manifest["excluded_videos"][0]["exclusion_reason"], "missing_subtitle")
            timing_path = workspace / manifest["videos"][0]["transcript_timing_file"]
            timing = json.loads(timing_path.read_text(encoding="utf-8"))
            self.assertTrue(timing["timed"])
            self.assertEqual(timing["lines"][0]["start_seconds"], 0.0)
            self.assertEqual(timing["lines"][0]["end_seconds"], 2.0)
            self.assertEqual(timing["lines"][0]["text"], "بیتکوین بالا می‌رود")
            self.assertEqual(manifest["videos"][0]["transcript_timing_sha256"], timing_path_sha256(timing_path))
            self.assertTrue(verify_audit_pack(settings)["verified"])

    def test_source_channel_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            raw = workspace / "raw"
            raw.mkdir()
            info_path = self.write_info(raw, "video-a", "تحلیل بیت‌کوین")
            payload = json.loads(info_path.read_text(encoding="utf-8"))
            payload["channel_id"] = "different-channel"
            info_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(SystemExit):
                build_manifest(self.make_settings(workspace))

    def test_unsafe_metadata_video_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            raw = workspace / "raw"
            raw.mkdir()
            info_path = self.write_info(raw, "video-a", "Synthetic title")
            payload = json.loads(info_path.read_text(encoding="utf-8"))
            payload["id"] = "../../outside"
            info_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Unsafe source metadata"):
                build_manifest(self.make_settings(workspace))


def timing_path_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
