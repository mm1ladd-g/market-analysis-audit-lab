from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from audit_lab.stages.classify import guess_category, load_category_config


class ClassificationTests(unittest.TestCase):
    def test_short_asset_token_does_not_match_inside_word(self) -> None:
        self.assertEqual(
            guess_category("video-1", "A method for reading whether markets are open"),
            "unknown",
        )
        self.assertEqual(guess_category("video-1", "ETH daily scenario"), "crypto")

    def test_persian_spacing_is_normalized_without_partial_word_match(self) -> None:
        self.assertEqual(guess_category("video-1", "تحلیل بیت‌کوین امروز"), "crypto")
        self.assertEqual(guess_category("video-1", "یک انسان در بازار"), "unknown")

    def test_invalid_or_empty_custom_rules_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "categories.json"
            path.write_text(json.dumps({"keyword_rules": {"crypto": [""]}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty or overlong"):
                load_category_config(path)

            path.write_text(json.dumps({"video_overrides": {"../../bad": "crypto"}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Video ID"):
                load_category_config(path)


if __name__ == "__main__":
    unittest.main()
