from __future__ import annotations

import unittest

from audit_lab.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_blank_optional_env_values_are_unset(self) -> None:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="",
            OPENAI_CLAIM_INPUT_USD_PER_1M="",
            OPENAI_SCORING_OUTPUT_USD_PER_1M="",
            MARKET_CSV_DIR="",
        )

        self.assertIsNone(settings.openai_api_key)
        self.assertIsNone(settings.openai_claim_input_usd_per_1m)
        self.assertIsNone(settings.openai_scoring_output_usd_per_1m)
        self.assertIsNone(settings.market_csv_dir)


if __name__ == "__main__":
    unittest.main()
