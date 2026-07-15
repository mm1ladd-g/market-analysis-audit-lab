from __future__ import annotations

import unittest

from audit_lab.stages.report import _hero_verdict


class HeroVerdictPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = {
            "total_videos": 72,
            "explicit_condition_percent": 81.7,
            "level_claim_percent": 94.6,
        }
        self.base = {
            "score": 48.41,
            "counted_claims": 347,
            "evidence_coverage_percent": 66.1,
            "at_least_partial_count": 243,
            "at_least_partial_percent": 70.0,
            "incorrect_count": 104,
        }

    def test_supportive_verdict_is_about_analytical_value_not_profit(self) -> None:
        verdict = _hero_verdict(self.base, self.scenario)
        self.assertEqual(verdict["key"], "supports_following")
        self.assertEqual(verdict["policy_version"], "hero-verdict-v1")
        self.assertEqual(verdict["missed_percent"], 30.0)
        self.assertFalse(verdict["profitability_measured"])

    def test_mixed_and_caution_thresholds_are_declared_before_the_subject(self) -> None:
        mixed = _hero_verdict(
            {**self.base, "score": 44.9, "at_least_partial_percent": 59.9},
            self.scenario,
        )
        caution = _hero_verdict(
            {**self.base, "score": 29.9, "at_least_partial_percent": 39.9},
            self.scenario,
        )
        self.assertEqual(mixed["key"], "mixed")
        self.assertEqual(caution["key"], "caution")

    def test_sparse_or_low_coverage_evidence_cannot_produce_a_recommendation(self) -> None:
        sparse = _hero_verdict({**self.base, "counted_claims": 29}, self.scenario)
        low_coverage = _hero_verdict(
            {**self.base, "evidence_coverage_percent": 49.9},
            self.scenario,
        )
        too_few_videos = _hero_verdict(self.base, {**self.scenario, "total_videos": 9})
        weak_structure = _hero_verdict(
            self.base,
            {**self.scenario, "explicit_condition_percent": 49.9},
        )
        self.assertEqual(sparse["key"], "insufficient")
        self.assertEqual(low_coverage["key"], "insufficient")
        self.assertEqual(too_few_videos["key"], "insufficient")
        self.assertEqual(weak_structure["key"], "mixed")


if __name__ == "__main__":
    unittest.main()
