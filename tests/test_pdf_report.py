from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from scripts.generate_audit_report import generate_report


class BilingualPdfReportTests(unittest.TestCase):
    def _workspace(self, payload: dict) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        workspace = Path(temp.name)
        reports = workspace / "reports"
        reports.mkdir(parents=True)
        (reports / "dashboard_data.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return temp, workspace

    def _synthetic_complete_payload(self) -> dict:
        return {
            "status": "audit_complete",
            "synthetic_demo": True,
            "notice": "All identities, prices, and results are fictional test data.",
            "project_name": "Synthetic Market Evidence Test",
            "analyst_name": "Fictional Research Presenter",
            "collection_id": "synthetic-collection-001",
            "date_range": {"start": "2024-01-01", "end": "2024-01-07"},
            "channel": {
                "id": "UC_SYNTHETIC_DEMO_NOT_REAL",
                "url": "https://example.invalid/synthetic-channel",
            },
            "scope": {
                "categories": ["crypto", "global_markets"],
                "source_videos_found": 2,
                "videos_in_scope_found": 2,
                "videos_audited": 2,
                "out_of_scope_videos": 0,
            },
            "audit_summary": {
                "score": 75.0,
                "total_claims": 3,
                "counted_claims": 2,
                "at_least_partial_percent": 100.0,
                "correct_count": 1,
                "partial_count": 1,
                "incorrect_count": 0,
            },
            "scenario_profile": {
                "explicit_condition_percent": 100.0,
                "level_claim_percent": 100.0,
                "invalidation_video_percent": 50.0,
                "both_directions_video_percent": 50.0,
            },
            "outcome_summary": {
                "available_series": 2,
                "complete_claims": 3,
                "providers": [
                    {
                        "name": "Synthetic deterministic fixture",
                        "resolution": "1 hour",
                        "series_count": 2,
                        "row_count": 96,
                    }
                ],
            },
            "verification": {
                "status": "verified",
                "verified": True,
                "file_hash_count": 8,
                "failed_file_hash_count": 0,
            },
            "tamper_evidence": {
                "manifest_sha256": "1" * 64,
                "archive_sha256": "2" * 64,
                "market_evidence_sha256": "3" * 64,
                "outcome_sha256": "4" * 64,
                "verification_status": "verified",
            },
            "limitations": [
                "AI-assisted extraction and scoring require human review and are not objective ground truth.",
                "Incomplete 24-hour outcome windows remain insufficient evidence.",
                "Market-data proxies may differ at exact boundary levels.",
            ],
        }

    def test_generates_persian_first_synthetic_report_without_brand_leakage(self) -> None:
        temp, workspace = self._workspace(self._synthetic_complete_payload())
        self.addCleanup(temp.cleanup)

        result = generate_report(workspace)
        output = workspace / "reports" / "audit-report.pdf"

        self.assertEqual(Path(result["output"]), output.resolve())
        self.assertTrue(output.is_file())
        self.assertGreater(output.stat().st_size, 25_000)
        self.assertTrue(result["synthetic_demo"])
        self.assertEqual(result["language_order"], ["fa", "en"])

        reader = PdfReader(str(output))
        self.assertGreaterEqual(len(reader.pages), 8)
        self.assertIn("Persian First, English Second", reader.metadata.title)
        self.assertIn("Scenario-outcome alignment", reader.metadata.subject)

        page_text = [page.extract_text() or "" for page in reader.pages]
        english_cover = next(
            index for index, text in enumerate(page_text)
            if "FULL EVIDENCE REPORT / ENGLISH EDITION" in text
        )
        self.assertGreater(english_cover, 0)
        joined = "\n".join(page_text)
        self.assertIn("SYNTHETIC DEMO", joined)
        self.assertIn("Scenario-outcome alignment is not a trading win rate", joined)
        self.assertIn("not certify analytical truth", joined)
        self.assertIn("Fictional Research Presenter", joined)
        image_objects = 0
        for page in reader.pages:
            resources = page.get("/Resources") or {}
            xobjects = resources.get("/XObject") or {}
            for reference in xobjects.values():
                if reference.get_object().get("/Subtype") == "/Image":
                    image_objects += 1
        self.assertEqual(image_objects, 0)

    def test_waiting_payload_produces_a_neutral_report_without_an_invented_score(self) -> None:
        payload = {
            "status": "waiting_for_manifest",
            "project_name": "Generic Audit Project",
            "analyst_name": "",
            "date_range": {"start": "2024-02-01", "end": "2024-02-10"},
            "channel": {"id": "", "url": ""},
            "message": "Run collection and manifest stages first.",
        }
        temp, workspace = self._workspace(payload)
        self.addCleanup(temp.cleanup)

        result = generate_report(workspace)
        output = Path(result["output"])
        reader = PdfReader(str(output))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertTrue(output.is_file())
        self.assertFalse(result["synthetic_demo"])
        self.assertIn("Waiting for source manifest", text)
        self.assertIn("No alignment index yet", text)
        self.assertIn("not a trading win rate", text)
        self.assertNotIn("75.0%", text)
        self.assertIn("Generic Audit Project", text)

    def test_partial_claims_payload_preserves_progress_without_a_verdict(self) -> None:
        payload = {
            "status": "claims_complete",
            "project_name": "Partial Audit Fixture",
            "analyst_name": "Test Source",
            "collection_id": "partial-001",
            "date_range": {"start": "2024-03-01", "end": "2024-03-05"},
            "channel": {"id": "UC_TEST_ONLY", "url": "https://example.invalid/test"},
            "scope": {
                "categories": ["crypto"],
                "source_videos_found": 4,
                "videos_audited": 4,
                "out_of_scope_videos": 0,
            },
            "scenario_profile": {
                "explicit_condition_percent": 80.0,
                "level_claim_percent": 90.0,
                "invalidation_video_percent": 50.0,
                "both_directions_video_percent": 50.0,
            },
            "verification": {"status": "verified", "verified": True},
        }
        temp, workspace = self._workspace(payload)
        self.addCleanup(temp.cleanup)

        result = generate_report(workspace)
        reader = PdfReader(result["output"])
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertIn("Claims extracted; outcome scoring pending", text)
        self.assertIn("No alignment index yet", text)
        self.assertIn("80.0%", text)
        self.assertNotIn("WEIGHTED ALIGNMENT INDEX", text)

    def test_identical_payload_produces_identical_pdf_bytes(self) -> None:
        payload = self._synthetic_complete_payload()
        first_temp, first_workspace = self._workspace(payload)
        second_temp, second_workspace = self._workspace(payload)
        self.addCleanup(first_temp.cleanup)
        self.addCleanup(second_temp.cleanup)

        first = Path(generate_report(first_workspace)["output"]).read_bytes()
        second = Path(generate_report(second_workspace)["output"]).read_bytes()

        self.assertEqual(hashlib.sha256(first).digest(), hashlib.sha256(second).digest())


if __name__ == "__main__":
    unittest.main()
