from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from audit_lab.utils.validation import sanitized_subprocess_env, youtube_channel_url, youtube_watch_url


class InputBoundaryTests(unittest.TestCase):
    def test_youtube_urls_are_canonicalized_and_host_allowlisted(self) -> None:
        self.assertEqual(
            youtube_channel_url("https://youtube.com/@example/videos"),
            "https://www.youtube.com/@example",
        )
        self.assertEqual(
            youtube_watch_url("https://youtu.be/video-123", "video-123"),
            "https://www.youtube.com/watch?v=video-123",
        )
        with self.assertRaises(ValueError):
            youtube_channel_url("https://youtube.com.evil.invalid/@example")
        with self.assertRaises(ValueError):
            youtube_watch_url("https://example.invalid/watch?v=video-123", "video-123")

    def test_subprocess_environment_does_not_inherit_api_credentials(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "synthetic-secret", "PATH": "/usr/bin", "LANG": "C.UTF-8"},
            clear=True,
        ):
            environment = sanitized_subprocess_env()
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertEqual(environment["PATH"], "/usr/bin")


if __name__ == "__main__":
    unittest.main()
