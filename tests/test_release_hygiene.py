from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class ReleaseHygieneTests(unittest.TestCase):
    def test_public_release_guard(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/check_public_release.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
