from __future__ import annotations

import unittest

from pydantic import ValidationError

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

    def test_private_mode_allows_missing_public_accountability(self) -> None:
        settings = Settings(
            _env_file=None,
            START_DATE="2024-01-01",
            END_DATE="2024-01-02",
            PUBLICATION_MODE="private",
            AUDIT_RELATIONSHIP_DISCLOSURE="",
            CORRECTION_CONTACT="",
            CORRECTION_POLICY_URL="",
        )

        self.assertIsNone(settings.audit_relationship_disclosure)
        self.assertIsNone(settings.correction_contact)
        self.assertIsNone(settings.correction_policy_url)

    def test_public_accountability_requires_disclosure_and_correction_channel(self) -> None:
        settings = Settings(
            _env_file=None,
            START_DATE="2024-01-01",
            END_DATE="2024-01-02",
            PUBLICATION_MODE="public",
        )

        with self.assertRaisesRegex(
            SystemExit,
            "AUDIT_RELATIONSHIP_DISCLOSURE, CORRECTION_CONTACT",
        ):
            settings.require_publication_accountability()

    def test_public_accountability_is_normalized_into_a_safe_dto(self) -> None:
        settings = Settings(
            _env_file=None,
            START_DATE="2024-01-01",
            END_DATE="2024-01-02",
            PUBLICATION_MODE="public",
            AUDIT_RELATIONSHIP_DISCLOSURE=(
                "This independent technical audit was commissioned  by the publisher;\n"
                "the analyst did not control its scoring."
            ),
            CORRECTION_CONTACT="Corrections@Example.COM",
            CORRECTION_POLICY_URL="https://AUDIT.EXAMPLE.COM/corrections",
        )

        self.assertEqual(
            settings.require_publication_accountability(),
            {
                "relationship_disclosure": settings.audit_relationship_disclosure,
                "correction_contact": "Corrections@example.com",
                "correction_contact_href": "mailto:Corrections@example.com",
                "correction_policy_url": "https://audit.example.com/corrections",
            },
        )

    def test_public_accountability_rejects_placeholders_and_unsafe_urls(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                AUDIT_RELATIONSHIP_DISCLOSURE="todo",
            )
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                CORRECTION_CONTACT="http://example.test/corrections",
            )
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                CORRECTION_POLICY_URL="https://user:secret@example.test/policy",
            )
        for url in (
            "https://localhost/corrections",
            "https://127.0.0.1/corrections",
            "https://10.0.0.8/corrections",
            "https://169.254.10.2/corrections",
            "https://example.test/corrections",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                Settings(_env_file=None, CORRECTION_CONTACT=url)
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                AUDIT_RELATIONSHIP_DISCLOSURE=(
                    "This otherwise meaningful relationship disclosure contains an unsafe "
                    "<script>alert(1)</script> payload."
                ),
            )


if __name__ == "__main__":
    unittest.main()
