from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audit_lab.demo import seed_synthetic_demo, synthetic_demo_settings
from audit_lab.stages.extract_claims import CLAIM_SCHEMA_VERSION, EVIDENCE_POLICY
from audit_lab.stages.score_claims import SCORING_POLICY, SCORING_SCHEMA_VERSION


class SyntheticDemoTests(unittest.TestCase):
    def test_demo_configuration_is_not_contaminated_by_operator_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PUBLICATION_MODE": "public",
                "ANALYST_NAME": "Real operator value",
                "START_DATE": "2026-01-01",
                "OPENAI_MODEL_SCORING": "operator-model",
            },
        ):
            settings = synthetic_demo_settings(Path("/tmp/fixed-demo"))
        self.assertEqual(settings.publication_mode, "private")
        self.assertEqual(settings.analyst_name, "Synthetic Research Presenter (fictional)")
        self.assertEqual(str(settings.start_date), "2024-01-01")
        self.assertEqual(settings.openai_scoring_model, "synthetic-offline-fixture")

    def test_demo_is_offline_complete_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            first = seed_synthetic_demo(workspace)
            second = seed_synthetic_demo(workspace)

            self.assertTrue(first["synthetic_demo"])
            self.assertTrue(first["collection_verified"])
            self.assertTrue(first["final_verified"])
            self.assertTrue(second["collection_verified"])
            self.assertTrue(second["final_verified"])
            self.assertTrue((workspace / "reports" / "dashboard_data.json").is_file())
            runtime = json.loads(
                (workspace / "final_audit" / "components" / "runtime_settings.public.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(runtime["analyst_name"], "Synthetic Research Presenter (fictional)")
            self.assertEqual(runtime["source"]["date_range"], {"start": "2024-01-01", "end": "2024-01-07"})
            self.assertEqual(runtime["source"]["channel_id"], "UC_SYNTHETIC_DEMO_NOT_REAL")
            extraction = json.loads(
                (workspace / "analysis" / "claims" / "extraction_run.json")
                .read_text(encoding="utf-8")
            )
            scoring = json.loads(
                (workspace / "analysis" / "scores" / "scoring_run.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(extraction["schema_version"], CLAIM_SCHEMA_VERSION)
            self.assertEqual(extraction["evidence_policy"], EVIDENCE_POLICY)
            self.assertEqual(extraction["human_review_required_claims"], 3)
            self.assertEqual(scoring["schema_version"], SCORING_SCHEMA_VERSION)
            self.assertEqual(scoring["scoring_policy"], SCORING_POLICY)
            score_rows = [
                json.loads(line)
                for line in (workspace / "analysis" / "scores" / "scores.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            self.assertEqual({row["evaluation_window"] for row in score_rows}, {"24h"})

    def test_demo_refuses_to_delete_non_demo_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            evidence = workspace / "real-evidence.json"
            evidence.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "Refusing to replace"):
                seed_synthetic_demo(workspace)

            self.assertEqual(evidence.read_text(encoding="utf-8"), "{}\n")

    def test_demo_allows_empty_setup_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "market-data").mkdir(parents=True)

            result = seed_synthetic_demo(workspace)

            self.assertTrue(result["final_verified"])

    def test_demo_marker_does_not_authorize_deleting_added_source_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            seed_synthetic_demo(workspace)
            added = workspace / "raw" / "real-video.info.json"
            added.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "raw source ledger"):
                seed_synthetic_demo(workspace)

            self.assertTrue(added.is_file())

    def test_quickstarts_do_not_promise_byte_identical_timestamped_bundles(self) -> None:
        english = Path("docs/en/quickstart.md").read_text(encoding="utf-8")
        farsi = Path("docs/fa/quickstart.md").read_text(encoding="utf-8")

        self.assertNotIn("Demo execution is deterministic", english)
        self.assertIn("UTC creation time", english)
        self.assertIn("هش بستهٔ کامل و PDF می‌تواند میان اجراها متفاوت باشد", farsi)


if __name__ == "__main__":
    unittest.main()
