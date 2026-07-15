from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audit_lab.stages.transcribe import _download_audio, _response_segments, segments_to_srt


class TimedTranscriptionTests(unittest.TestCase):
    def test_segments_render_as_timed_srt(self) -> None:
        payload = segments_to_srt([
            {"start": 0.0, "end": 1.25, "text": "  First   sentence. "},
            {"start": 61.001, "end": 62.5, "text": "Second sentence."},
        ])
        self.assertIn("00:00:00,000 --> 00:00:01,250", payload)
        self.assertIn("00:01:01,001 --> 00:01:02,500", payload)
        self.assertIn("First sentence.", payload)

    def test_chunk_offset_is_applied_to_api_segments(self) -> None:
        response = SimpleNamespace(segments=[SimpleNamespace(start=1.0, end=3.0, text="hello")])
        rows = _response_segments(response, offset=1200.0, fallback_duration=10.0)
        self.assertEqual(rows[0]["start"], 1201.0)
        self.assertEqual(rows[0]["end"], 1203.0)

    def test_empty_segment_response_uses_transcript_text(self) -> None:
        response = SimpleNamespace(segments=[], text="fallback text")
        rows = _response_segments(response, offset=600.0, fallback_duration=25.0)
        self.assertEqual(rows, [{"start": 600.0, "end": 625.0, "text": "fallback text"}])

    def test_audio_download_rejects_untrusted_metadata_url_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            info_path = Path(tmp) / "20240101__video-123.info.json"
            info_path.write_text("{}\n", encoding="utf-8")
            with patch("audit_lab.stages.transcribe.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "expected HTTPS YouTube video"):
                    _download_audio(
                        {"id": "video-123", "webpage_url": "https://example.invalid/audio"},
                        info_path,
                    )
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
