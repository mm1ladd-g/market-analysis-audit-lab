from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from audit_lab import web
from audit_lab.demo import seed_synthetic_demo
from audit_lab.settings import Settings
from audit_lab.stages.finalize import (
    finalize_audit,
    get_human_review_status,
    get_publication_review_status,
    record_human_review,
    record_publication_review,
    verify_final_audit,
)
from audit_lab.stages.report import _outcome_presentation, write_dashboard_data
from audit_lab.utils.hash import sha256_file, sha256_json
from audit_lab.utils.jsonio import write_json_atomic


def demo_settings(workspace: Path, *, publication_mode: str = "private", **values) -> Settings:
    return Settings(
        PROJECT_NAME="Market Analysis Audit Lab · Synthetic Demo",
        ANALYST_NAME="Synthetic Research Presenter (fictional)",
        YOUTUBE_CHANNEL_URL="https://example.invalid/synthetic-channel",
        YOUTUBE_CHANNEL_ID="UC_SYNTHETIC_DEMO_NOT_REAL",
        START_DATE="2024-01-01",
        END_DATE="2024-01-07",
        WORKSPACE_DIR=workspace,
        SOURCE_RIGHTS_ACKNOWLEDGED=True,
        AUDIT_SCOPE_CATEGORIES="crypto,global_markets",
        AUDIT_MODE="offline",
        PUBLICATION_MODE=publication_mode,
        **values,
    )


class PublicDashboardBoundaryTests(unittest.TestCase):
    def _finalize_public_demo(
        self,
        workspace: Path,
        *,
        public_claim_ledger: bool = False,
    ) -> Settings:
        seed_synthetic_demo(workspace)
        settings = demo_settings(
            workspace,
            publication_mode="public",
            PUBLIC_CLAIM_LEDGER=public_claim_ledger,
            SOURCE_MODE="youtube",
            OPENAI_MODEL_CLAIM_EXTRACTION="synthetic-offline-fixture",
            OPENAI_MODEL_SCORING="synthetic-offline-fixture",
        )
        write_dashboard_data(settings)
        record_human_review(
            settings,
            action="accepted",
            reviewer="Evidence reviewer",
            notes="Accepted the exact synthetic evidence set.",
        )
        write_dashboard_data(settings)
        (settings.reports_dir / "audit-report.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        publication = record_publication_review(
            settings,
            reviewer="Publication reviewer",
            notes="Inspected the finished dashboard, PDF, and enabled public artifacts.",
        )
        self.assertTrue(publication["accepted_for_current_artifacts"])
        finalize_audit(settings)
        return settings

    def test_presentation_service_disables_schema_routes_and_sets_security_headers(self) -> None:
        client = TestClient(web.app)
        response = client.get("/openapi.json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])

    def test_dashboard_dto_is_an_allowlist_not_a_redacted_private_dump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active = Settings(
                WORKSPACE_DIR=Path(tmp),
                START_DATE="2024-01-01",
                END_DATE="2024-01-02",
                PUBLICATION_MODE="private",
                PUBLIC_CLAIM_LEDGER=False,
            )
            payload = {
                "status": "audit_complete",
                "project_name": "Public audit",
                "date_range": {"start": "2024-01-01", "end": "2024-01-02"},
                "audit_summary": {"total_claims": 1, "counted_claims": 1, "categories": []},
                "scenario_profile": {"total_claims": 1, "total_videos": 1},
                "human_review": {"accepted_for_current_artifacts": False},
                "claims": {"secret": "claim text must not cross the boundary"},
                "outcomes": {"error": "/Users/operator/private.csv"},
                "scores": {"reasoning": "private chain of thought"},
                "result_examples": [{
                    "claim_text": "secret prediction",
                    "source_excerpt": "copyright excerpt",
                    "reasoning": "private reasoning",
                    "video_url": "https://user:pass@example.test/watch?v=1&token=secret#fragment",
                }],
                "run_summary": {"zip_path": "/Users/operator/private.zip"},
                "verification": {
                    "verified": True,
                    "failed_files": ["/Users/operator/private.txt"],
                    "error": "private failure",
                },
            }
            with patch.object(web, "settings", active):
                result = web._public_dashboard_dto(payload)
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertEqual(result["status"], "private_preview")
            for forbidden in (
                "claim text must not",
                "secret prediction",
                "copyright excerpt",
                "private reasoning",
                "video_url",
                "token=secret",
                "/Users/operator",
                "private failure",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_urls_drop_userinfo_query_and_fragment(self) -> None:
        value = web._redact_text(
            "https://alice:secret@example.test:8443/watch?v=abc&token=x#part",
            Settings(START_DATE="2024-01-01", END_DATE="2024-01-02"),
        )
        self.assertEqual(value, "https://example.test:8443/watch")

    def test_claim_ledger_requires_public_mode_review_and_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active = Settings(
                WORKSPACE_DIR=Path(tmp),
                START_DATE="2024-01-01",
                END_DATE="2024-01-02",
                PUBLICATION_MODE="public",
                PUBLIC_CLAIM_LEDGER=False,
            )
            with patch.object(web, "settings", active):
                with self.assertRaises(HTTPException) as context:
                    web.claims_api()
            self.assertEqual(context.exception.status_code, 404)

    def test_pdf_replacement_closes_dashboard_report_and_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._finalize_public_demo(Path(tmp) / "workspace")
            with patch.object(web, "settings", settings):
                client = TestClient(web.app)
                self.assertTrue(client.get("/api/dashboard").json()["publication"]["ready"])
                self.assertEqual(client.get("/report").status_code, 200)
                (settings.reports_dir / "audit-report.pdf").write_bytes(
                    b"%PDF-1.4\nreplaced\n%%EOF\n"
                )
                closed = client.get("/api/dashboard")
                self.assertEqual(closed.status_code, 200)
                self.assertEqual(closed.json()["status"], "publication_unavailable")
                self.assertFalse(closed.json()["publication"]["ready"])
                self.assertEqual(client.get("/report").status_code, 404)
            self.assertEqual(get_publication_review_status(settings)["status"], "stale")
            with self.assertRaisesRegex(SystemExit, "exact dashboard, PDF"):
                finalize_audit(settings)

    def test_dashboard_replacement_closes_every_public_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._finalize_public_demo(Path(tmp) / "workspace")
            dashboard_path = settings.reports_dir / "dashboard_data.json"
            dashboard_payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
            dashboard_payload["project_name"] = "Unreviewed replacement"
            write_json_atomic(dashboard_path, dashboard_payload)
            with patch.object(web, "settings", settings):
                client = TestClient(web.app)
                closed = client.get("/api/dashboard")
                self.assertEqual(closed.json()["status"], "publication_unavailable")
                self.assertNotIn("Unreviewed replacement", closed.text)
                self.assertEqual(client.get("/report").status_code, 404)
            self.assertEqual(get_publication_review_status(settings)["status"], "stale")
            with self.assertRaisesRegex(SystemExit, "exact dashboard, PDF"):
                finalize_audit(settings)

    def test_optional_ledger_replacement_closes_dashboard_claims_and_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._finalize_public_demo(
                Path(tmp) / "workspace",
                public_claim_ledger=True,
            )
            with patch.object(web, "settings", settings):
                client = TestClient(web.app)
                self.assertTrue(client.get("/api/dashboard").json()["publication"]["ready"])
                self.assertEqual(client.get("/api/claims").status_code, 200)
                ledger = settings.claims_dir / "claims.jsonl"
                ledger.write_text(ledger.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                closed = client.get("/api/dashboard")
                self.assertEqual(closed.json()["status"], "publication_unavailable")
                self.assertEqual(client.get("/api/claims").status_code, 404)
                self.assertEqual(client.get("/report").status_code, 404)
            self.assertEqual(get_publication_review_status(settings)["status"], "stale")
            with self.assertRaisesRegex(SystemExit, "human accepts the current artifact binding"):
                finalize_audit(settings)

    def test_dashboard_completeness_requires_one_selected_window_for_all_assets(self) -> None:
        outcomes = {
            "claims": [{
                "claim_id": "c1",
                "assets": [
                    {
                        "status": "available",
                        "window_24h": {"complete": True},
                        "window_48h": {"complete": True},
                    },
                    {
                        "status": "available",
                        "window_24h": {"complete": False},
                        "window_48h": {"complete": True},
                    },
                ],
            }],
            "series": {},
            "providers": [],
        }
        claims = {"c1": {"claim_id": "c1", "time_horizon": "next 24 hours", "normalized_horizon_hours": 24}}
        self.assertEqual(_outcome_presentation(outcomes, claims)["complete_claims"], 0)
        outcomes["claims"][0]["assets"][1]["window_24h"]["complete"] = True
        self.assertEqual(_outcome_presentation(outcomes, claims)["complete_claims"], 1)


class ReviewAndFinalizationTests(unittest.TestCase):
    def test_review_acceptance_is_hash_bound_and_becomes_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            seed_synthetic_demo(workspace)
            settings = demo_settings(workspace)
            status = record_human_review(
                settings,
                action="accepted",
                reviewer="Test reviewer",
                notes="Reviewed synthetic evidence and presentation.",
            )
            self.assertTrue(status["accepted_for_current_artifacts"])
            self.assertTrue(status["ledger_valid"])

            public_status = get_human_review_status(
                demo_settings(workspace, publication_mode="public")
            )
            self.assertEqual(public_status["status"], "stale")
            self.assertFalse(public_status["accepted_for_current_artifacts"])

            ledger = settings.scores_dir / "scores.jsonl"
            ledger.write_text(ledger.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            stale = get_human_review_status(settings)
            self.assertEqual(stale["status"], "stale")
            self.assertFalse(stale["accepted_for_current_artifacts"])

    def test_public_finalize_fails_closed_without_current_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            seed_synthetic_demo(workspace)
            settings = demo_settings(workspace, publication_mode="public")
            with self.assertRaisesRegex(SystemExit, "human accepts the current artifact binding"):
                finalize_audit(settings)

    def test_review_metadata_rejects_credential_like_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            seed_synthetic_demo(workspace)
            settings = demo_settings(workspace)
            with self.assertRaisesRegex(SystemExit, "credential"):
                record_human_review(
                    settings,
                    action="accepted",
                    reviewer="Test reviewer",
                    notes="sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz123456",
                )

    def test_finalize_reconciles_per_video_and_aggregate_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            seed_synthetic_demo(workspace)
            settings = demo_settings(workspace)
            ledger = settings.scores_dir / "scores.jsonl"
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
            rows[0]["evidence_summary"] = "tampered aggregate row"
            ledger.write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "score ledger differs from per-video"):
                finalize_audit(settings)

    def test_final_bundle_copies_verified_market_sources_and_sanitizes_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            seed_synthetic_demo(workspace)
            settings = demo_settings(
                workspace,
                OPENAI_API_KEY="test-secret-key",
                TRANSCRIPTION_PROMPT="private transcription hint",
            )
            source = settings.outcomes_dir / "market_data" / "verified-fixture.json"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('{"rows":[1,2,3]}\n', encoding="utf-8")
            source_hash = sha256_file(source)
            outcomes_path = settings.outcomes_dir / "claim_outcomes.json"
            outcomes = json.loads(outcomes_path.read_text(encoding="utf-8"))
            for claim in outcomes["claims"]:
                for asset in claim["assets"]:
                    if asset.get("status") == "available":
                        asset["source_file"] = str(source.relative_to(workspace))
                        asset["source_sha256"] = source_hash
            outcomes.pop("outcome_snapshot_sha256", None)
            outcomes.pop("market_evidence_snapshot_sha256", None)
            outcomes["market_evidence_snapshot_sha256"] = sha256_json(outcomes)
            outcomes["outcome_snapshot_sha256"] = sha256_json(outcomes)
            write_json_atomic(outcomes_path, outcomes)

            finalize_audit(settings)
            market_manifest = json.loads(
                (workspace / "final_audit" / "components" / "market_evidence" / "manifest.json")
                .read_text(encoding="utf-8")
            )
            matching = [row for row in market_manifest["files"] if row["sha256"] == source_hash]
            self.assertEqual(len(matching), 1)
            copied = workspace / "final_audit" / "components" / "market_evidence" / matching[0]["copied_file"]
            self.assertEqual(sha256_file(copied), source_hash)

            runtime = (
                workspace / "final_audit" / "components" / "runtime_settings.public.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn("test-secret-key", runtime)
            self.assertNotIn("private transcription hint", runtime)
            self.assertNotIn(str(workspace), runtime)
            self.assertTrue(verify_final_audit(settings)["verified"])


if __name__ == "__main__":
    unittest.main()
