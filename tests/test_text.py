from __future__ import annotations

import unittest

from audit_lab.utils.text import canonicalize_subtitle


class SubtitleCanonicalizationTests(unittest.TestCase):
    def test_vtt_cue_identifiers_are_not_mistaken_for_transcript_text(self) -> None:
        text, rows = canonicalize_subtitle(
            "WEBVTT\n\nintro-cue\n00:00.000 --> 00:02.500 align:start\nFirst line.\n\n"
            "next-cue\n00:02.500 --> 00:04.000\nSecond line.\n"
        )
        self.assertEqual(text, "First line.\nSecond line.")
        self.assertEqual(rows[0]["start_seconds"], 0.0)
        self.assertEqual(rows[1]["end_seconds"], 4.0)

    def test_plain_text_has_explicit_null_timing(self) -> None:
        text, rows = canonicalize_subtitle("Line one.\nLine two.\n")
        self.assertEqual(text, "Line one.\nLine two.")
        self.assertIsNone(rows[0]["start_seconds"])
        self.assertIsNone(rows[0]["end_seconds"])


if __name__ == "__main__":
    unittest.main()
