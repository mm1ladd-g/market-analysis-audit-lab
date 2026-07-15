from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from audit_lab.models.scoring import ClaimScoreCandidate, ModelVideoScoring
from audit_lab.settings import Settings
from audit_lab.stages.extract_claims import CLAIM_SCHEMA_VERSION, EVIDENCE_POLICY
from audit_lab.stages.extract_claims import PROMPT_PATH as CLAIM_PROMPT_PATH
from audit_lab.stages.fetch_outcomes import (
    _level_numbers,
    _parse_binance_api_rows,
    _parse_binance_csv,
    _validate_binance_symbol,
    _validate_series_key,
    _window,
    fetch_csv_series,
    fetch_market_outcomes,
    load_asset_registry,
    resolve_asset,
)
from audit_lab.stages.score_claims import (
    PROMPT_PATH,
    SCORING_POLICY,
    SCORING_SCHEMA_VERSION,
    ScoringContractError,
    deterministic_exclusion,
    outcome_supports_window,
    required_evaluation_window,
    run_scoring,
    scoring_input_fingerprint,
    validate_video_scoring,
)
from audit_lab.utils.hash import sha256_text

NON_CONTINUOUS_HOURLY = {
    "session_type": "non_continuous",
    "cadence_seconds": 3600,
    "maximum_gap_seconds": 72 * 3600,
    "boundary_tolerance_seconds": 24 * 3600,
    "minimum_bars_per_24h": 4,
    "declaration_source": "unit test",
}

CONTINUOUS_ONE_MINUTE = {
    "session_type": "continuous",
    "cadence_seconds": 60,
    "maximum_gap_seconds": 60,
    "boundary_tolerance_seconds": 60,
    "minimum_bars_per_24h": 1440,
    "declaration_source": "unit test",
}


class OutcomeWindowTests(unittest.TestCase):
    def test_binance_rows_are_shape_and_ohlc_validated(self) -> None:
        archive_payload = (
            b"open_time,open,high,low,close,volume,close_time,quote_volume,trades\n"
            b"1717200000000,100,102,99,101,10,1717200059999,1000,12\n"
        )
        rows = _parse_binance_csv(archive_payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["high"], 102.0)
        with self.assertRaises(ValueError):
            _parse_binance_csv(archive_payload + b"not-a-time,1,1,1,1,1,1,1,1\n")
        with self.assertRaises(ValueError):
            _parse_binance_api_rows([[1717200000000, "100"]])

    def test_complete_window_uses_first_tradable_bar(self) -> None:
        anchor = datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)
        rows = []
        for hour in range(26):
            price = 100 + hour
            rows.append({
                "timestamp_utc": (datetime(2026, 6, 1, 11, tzinfo=timezone.utc) + timedelta(hours=hour)).isoformat(),
                "open": price,
                "high": price + 2,
                "low": price - 1,
                "close": price + 1,
                "volume": 1,
            })
        result = _window(
            rows, anchor, 24, anchor + timedelta(hours=50),
            coverage_policy={**NON_CONTINUOUS_HOURLY, "minimum_bars_per_24h": 24},
        )
        self.assertTrue(result["complete"])
        self.assertEqual(result["open"], 100)
        self.assertEqual(result["high"], 125)
        self.assertEqual(result["low"], 99)

    def test_window_is_half_open_at_horizon(self) -> None:
        anchor = datetime(2026, 6, 1, 0, tzinfo=timezone.utc)
        rows = [
            {"timestamp_utc": anchor.isoformat(), "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp_utc": (anchor + timedelta(hours=24)).isoformat(), "open": 100, "high": 999, "low": 1, "close": 500},
        ]
        result = _window(
            rows, anchor, 24, anchor + timedelta(hours=48),
            coverage_policy=NON_CONTINUOUS_HOURLY,
        )
        self.assertEqual(result["high"], 101)
        self.assertEqual(result["low"], 99)

    def test_window_is_not_complete_before_horizon(self) -> None:
        anchor = datetime(2026, 7, 13, 10, tzinfo=timezone.utc)
        rows = [{
            "timestamp_utc": anchor.isoformat(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1,
        }]
        result = _window(
            rows, anchor, 24, anchor + timedelta(hours=2),
            coverage_policy=NON_CONTINUOUS_HOURLY,
        )
        self.assertFalse(result["complete"])
        self.assertEqual(result["status"], "window_not_elapsed")

    def test_continuous_window_with_source_gap_is_not_complete(self) -> None:
        anchor = datetime(2026, 6, 1, 0, tzinfo=timezone.utc)
        rows = [
            {"timestamp_utc": (anchor + timedelta(minutes=index)).isoformat(), "open": 100, "high": 101, "low": 99, "close": 100}
            for index in range(20)
        ]
        result = _window(
            rows, anchor, 1, anchor + timedelta(hours=2), continuous=True,
            coverage_policy=CONTINUOUS_ONE_MINUTE,
        )
        self.assertFalse(result["complete"])
        self.assertEqual(result["status"], "source_coverage_gap")

    def test_window_records_ordered_level_events(self) -> None:
        anchor = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        rows = [
            {"timestamp_utc": anchor.isoformat(), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"timestamp_utc": (anchor + timedelta(minutes=1)).isoformat(), "open": 100, "high": 106, "low": 100, "close": 105, "volume": 1},
            {"timestamp_utc": (anchor + timedelta(minutes=2)).isoformat(), "open": 105, "high": 105, "low": 94, "close": 95, "volume": 1},
        ]
        result = _window(
            rows, anchor, 1, anchor + timedelta(hours=2), ["۱۰۵", "95"],
            coverage_policy={
                **NON_CONTINUOUS_HOURLY,
                "cadence_seconds": 60,
                "maximum_gap_seconds": 3600,
                "boundary_tolerance_seconds": 3600,
                "minimum_bars_per_24h": 144,
            },
        )
        events = {row["level"]: row for row in result["level_events"]}
        self.assertEqual(events[105.0]["first_touch_utc"], (anchor + timedelta(minutes=1)).isoformat())
        self.assertEqual(events[95.0]["first_close_below_utc"], None)
        self.assertEqual(result["high_timestamp_utc"], (anchor + timedelta(minutes=1)).isoformat())

    def test_iran_market_is_not_silently_proxied(self) -> None:
        self.assertIsNone(resolve_asset("USDIRR"))
        self.assertIsNone(resolve_asset("USDT-IRR"))
        self.assertEqual(resolve_asset("BTC-USD")[0], "BTC-USD")

    def test_supported_global_indexes_use_explicit_symbols(self) -> None:
        self.assertEqual(resolve_asset("VIX")[0], "^VIX")
        self.assertEqual(resolve_asset("DOWJONES")[0], "^DJI")
        self.assertEqual(resolve_asset("DJIA")[0], "^DJI")
        self.assertEqual(resolve_asset("BRENT")[0], "BZ=F")
        self.assertEqual(resolve_asset("ETH/BTC")[0], "ETH-BTC")

    def test_non_price_numbers_are_not_treated_as_price_levels(self) -> None:
        self.assertEqual(_level_numbers(["70% confidence", "24 hours", "year 2026", "price 105.5"]), [105.5])

    def test_price_level_2000_is_not_mistaken_for_a_year(self) -> None:
        self.assertEqual(_level_numbers(["support at 2000", "year 2026"]), [2000.0])

    def test_continuous_cadence_is_declared_not_inferred_from_sparse_rows(self) -> None:
        anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [
            {
                "timestamp_utc": (anchor + timedelta(minutes=index * 10)).isoformat(),
                "open": 100, "high": 101, "low": 99, "close": 100,
            }
            for index in range(6)
        ]
        result = _window(
            rows, anchor, 1, anchor + timedelta(hours=2), continuous=True,
            coverage_policy=CONTINUOUS_ONE_MINUTE,
        )
        self.assertFalse(result["complete"])
        self.assertIn("gap_exceeds_declared_session_maximum", result["coverage"]["reasons"])
        self.assertEqual(result["coverage"]["minimum_required_bars"], 60)

    def test_complete_continuous_window_requires_every_declared_bar(self) -> None:
        anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [
            {
                "timestamp_utc": (anchor + timedelta(minutes=index)).isoformat(),
                "open": 100, "high": 101, "low": 99, "close": 100,
            }
            for index in range(60)
        ]
        result = _window(
            rows, anchor, 1, anchor + timedelta(hours=2), continuous=True,
            coverage_policy=CONTINUOUS_ONE_MINUTE,
        )
        self.assertTrue(result["complete"])
        self.assertEqual(result["coverage"]["cadence_seconds"], 60.0)

    def test_non_continuous_series_requires_declared_session_policy(self) -> None:
        anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [{"timestamp_utc": anchor.isoformat(), "open": 1, "high": 1, "low": 1, "close": 1}]
        result = _window(rows, anchor, 24, anchor + timedelta(hours=25))
        self.assertEqual(result["status"], "coverage_policy_missing")
        self.assertFalse(result["complete"])

    def test_non_continuous_policy_cannot_declare_a_token_bar_minimum(self) -> None:
        anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [{"timestamp_utc": anchor.isoformat(), "open": 1, "high": 1, "low": 1, "close": 1}]
        result = _window(
            rows, anchor, 24, anchor + timedelta(hours=25),
            coverage_policy={**NON_CONTINUOUS_HOURLY, "minimum_bars_per_24h": 2},
        )
        self.assertEqual(result["status"], "coverage_policy_invalid")
        self.assertIn("10%", result["coverage_note"])

    def test_non_continuous_series_rejects_undeclared_large_session_gap(self) -> None:
        anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [
            {"timestamp_utc": anchor.isoformat(), "open": 1, "high": 1, "low": 1, "close": 1},
            {
                "timestamp_utc": (anchor + timedelta(hours=12)).isoformat(),
                "open": 1, "high": 1, "low": 1, "close": 1,
            },
        ]
        policy = {
            **NON_CONTINUOUS_HOURLY,
            "maximum_gap_seconds": 6 * 3600,
        }
        result = _window(rows, anchor, 24, anchor + timedelta(hours=25), coverage_policy=policy)
        self.assertFalse(result["complete"])
        self.assertIn("gap_exceeds_declared_session_maximum", result["coverage"]["reasons"])

    def test_duplicate_timestamps_and_bad_ohlc_are_rejected(self) -> None:
        anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        duplicate = [
            {"timestamp_utc": anchor.isoformat(), "open": 1, "high": 2, "low": 1, "close": 2},
            {"timestamp_utc": anchor.isoformat(), "open": 2, "high": 2, "low": 1, "close": 1},
        ]
        bad_ohlc = [{"timestamp_utc": anchor.isoformat(), "open": 10, "high": 9, "low": 8, "close": 10}]
        self.assertEqual(
            _window(duplicate, anchor, 1, anchor + timedelta(hours=2), coverage_policy=NON_CONTINUOUS_HOURLY)["status"],
            "invalid_market_series",
        )
        self.assertEqual(
            _window(bad_ohlc, anchor, 1, anchor + timedelta(hours=2), coverage_policy=NON_CONTINUOUS_HOURLY)["status"],
            "invalid_market_series",
        )

    def test_naive_timestamp_is_rejected(self) -> None:
        anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [{"timestamp_utc": "2026-06-01T00:00:00", "open": 1, "high": 1, "low": 1, "close": 1}]
        result = _window(rows, anchor, 1, anchor + timedelta(hours=2), coverage_policy=NON_CONTINUOUS_HOURLY)
        self.assertEqual(result["status"], "invalid_market_series")


class CsvMarketEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = self.root / "workspace"
        self.market_dir = self.workspace / "analysis" / "outcomes" / "market_data"
        self.csv_dir = self.root / "licensed-input"
        self.market_dir.mkdir(parents=True)
        self.csv_dir.mkdir()
        self.start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=2)
        self.now = self.end + timedelta(days=1)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_sidecar(self, *, series_key: str = "TEST", **overrides) -> None:
        payload = {
            "schema_version": "1.0",
            "series_key": series_key,
            "symbol": "TEST",
            "venue": "Example Licensed Venue",
            "timezone": "UTC",
            "interval": "1h",
            "cadence_seconds": 3600,
            "timestamp_semantics": "bar_open",
            "session": {
                "type": "non_continuous",
                "maximum_gap_seconds": 86400,
                "boundary_tolerance_seconds": 86400,
                "minimum_bars_per_24h": 4,
            },
            "license": {"name": "Operator test license", "redistribution": "derived_only"},
        }
        payload.update(overrides)
        (self.csv_dir / "TEST.metadata.json").write_text(json.dumps(payload), encoding="utf-8")

    def _write_csv(self, rows: list[str] | None = None) -> None:
        lines = ["timestamp_utc,open,high,low,close,volume"]
        lines.extend(rows or [
            "2026-06-01T00:00:00+00:00,100,102,99,101,10",
            "2026-06-01T01:00:00+00:00,101,103,100,102,11",
            "2026-06-01T02:00:00+00:00,102,104,101,103,12",
            "2026-06-01T03:00:00+00:00,103,105,102,104,13",
        ])
        (self.csv_dir / "TEST.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _fetch(self, series_key: str = "TEST") -> dict:
        return fetch_csv_series(
            series_key, self.start, self.end, self.now,
            self.market_dir, self.workspace, self.csv_dir,
        )

    def test_valid_csv_requires_and_preserves_sidecar_provenance(self) -> None:
        self._write_csv()
        self._write_sidecar()
        result = self._fetch()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["interval"], "1h")
        self.assertEqual(result["coverage_policy"]["cadence_seconds"], 3600.0)
        self.assertEqual(result["license"]["redistribution"], "derived_only")
        self.assertTrue((self.workspace / result["source_file"]).is_file())

    def test_missing_sidecar_is_not_accepted(self) -> None:
        self._write_csv()
        result = self._fetch()
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("sidecar", result["error"])

    def test_duplicate_timestamp_and_invalid_ohlc_are_not_repaired(self) -> None:
        self._write_sidecar()
        self._write_csv([
            "2026-06-01T00:00:00+00:00,100,99,98,100,10",
            "2026-06-01T00:00:00+00:00,100,101,99,100,10",
        ])
        result = self._fetch()
        self.assertEqual(result["status"], "unavailable")
        self.assertRegex(result["error"], "OHLC|duplicate")

    def test_sidecar_rejects_bad_timezone_and_missing_license(self) -> None:
        self._write_csv()
        self._write_sidecar(timezone="Not/A_Real_Zone")
        self.assertEqual(self._fetch()["status"], "unavailable")
        self._write_sidecar(license=None)
        result = self._fetch()
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("license", result["error"])

    def test_bar_close_timestamps_are_normalized_to_bar_open(self) -> None:
        self._write_csv(["2026-06-01T01:00:00+00:00,100,101,99,100,10"])
        self._write_sidecar(timestamp_semantics="bar_close")
        result = self._fetch()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["rows"][0]["timestamp_utc"], "2026-06-01T00:00:00+00:00")
        self.assertEqual(result["input_timestamp_semantics"], "bar_close")

    def test_series_key_and_binance_symbol_reject_path_or_url_input(self) -> None:
        for value in ("../../escape", "https://example.test", "A/B", ".."):
            with self.assertRaises(ValueError):
                _validate_series_key(value)
        for value in ("../BTCUSDT", "btcusdt", "BTC/USDT", "httpsBTCUSDT"):
            with self.assertRaises(ValueError):
                _validate_binance_symbol(value)
        result = self._fetch("../../escape")
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse((self.root / "escape.csv-normalized.json").exists())

    def test_normalized_output_cannot_follow_a_symlink_outside_workspace(self) -> None:
        self._write_csv()
        self._write_sidecar()
        outside = self.root / "outside.json"
        outside.write_text("sentinel", encoding="utf-8")
        (self.market_dir / "TEST.csv-normalized.json").symlink_to(outside)
        result = self._fetch()
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("configured root", result["error"])
        self.assertEqual(outside.read_text(encoding="utf-8"), "sentinel")

    def test_asset_registry_rejects_unsafe_binance_mapping(self) -> None:
        mapping = self.root / "assets.json"
        mapping.write_text(json.dumps({
            "asset_sources": {"BTC": {"series_key": "../../escape"}},
            "binance_series": {"BTC-USD": "BTC/USDT"},
        }), encoding="utf-8")
        settings = Settings(_env_file=None, ASSET_MAP_FILE=mapping)
        with self.assertRaises(ValueError):
            load_asset_registry(settings)


class MarketOutcomeIntegrationTests(unittest.TestCase):
    def test_injected_hourly_provider_produces_validated_hashed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            settings = Settings(
                _env_file=None,
                WORKSPACE_DIR=workspace,
                START_DATE=date(2026, 6, 1),
                END_DATE=date(2026, 6, 1),
                INTERNATIONAL_MARKET_PROVIDER="yfinance",
            )
            settings.pack_dir.mkdir(parents=True)
            settings.claims_dir.mkdir(parents=True)
            manifest = {
                "collection_id": "test-collection",
                "videos": [{
                    "video_id": "video-1",
                    "category": "global_markets",
                    "published_at_utc": "2026-06-01T00:00:00+00:00",
                    "published_at_source": "operator_provided_timestamp",
                }],
            }
            (settings.pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (settings.claims_dir / "extraction_run.json").write_text(json.dumps({
                "collection_id": "test-collection", "status": "complete",
            }), encoding="utf-8")
            (settings.claims_dir / "claims.jsonl").write_text(json.dumps({
                "claim_id": "video-1-c001",
                "video_id": "video-1",
                "category": "global_markets",
                "assets": ["XAUUSD"],
                "levels": ["support 2000"],
            }) + "\n", encoding="utf-8")

            anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
            index = pd.date_range(anchor, periods=49, freq="1h")
            frame = pd.DataFrame({
                "Open": [2000.0] * 49,
                "High": [2002.0] * 49,
                "Low": [1998.0] * 49,
                "Close": [2001.0] * 49,
                "Volume": [100.0] * 49,
            }, index=index)

            def history_fetcher(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
                self.assertEqual(ticker, "GC=F")
                self.assertLess(start, end)
                return frame

            output_path = fetch_market_outcomes(
                settings,
                history_fetcher=history_fetcher,
                as_of=anchor + timedelta(days=4),
            )
            output = json.loads(output_path.read_text(encoding="utf-8"))
            market_series = output["series"]["GC=F"]
            self.assertEqual(market_series["validation"]["ohlc_ordering"], "passed")
            self.assertEqual(market_series["coverage_policy"]["cadence_seconds"], 3600.0)
            self.assertTrue((workspace / market_series["source_file"]).is_file())
            asset = output["claims"][0]["assets"][0]
            self.assertTrue(asset["window_24h"]["complete"])
            self.assertTrue(asset["window_48h"]["complete"])
            self.assertEqual(asset["window_24h"]["level_events"][0]["level"], 2000.0)


class ScoringContractTests(unittest.TestCase):
    def test_scoring_fingerprint_ignores_storage_hash_but_not_market_values(self) -> None:
        settings = Settings(_env_file=None)
        video = {"video_id": "v"}
        claims = [{"claim_id": "v-c001", "claim_text": "BTC rises"}]
        outcome = {"claim_id": "v-c001", "assets": [{"status": "available", "source_sha256": "a", "window_24h": {"complete": True, "close": 105}}]}
        first = scoring_input_fingerprint(settings=settings, prompt_sha256="p", video=video, claims=claims, outcomes=[outcome])
        outcome["assets"][0]["source_sha256"] = "b"
        second = scoring_input_fingerprint(settings=settings, prompt_sha256="p", video=video, claims=claims, outcomes=[outcome])
        self.assertEqual(first, second)
        outcome["assets"][0]["window_24h"]["close"] = 95
        third = scoring_input_fingerprint(settings=settings, prompt_sha256="p", video=video, claims=claims, outcomes=[outcome])
        self.assertNotEqual(first, third)

    def test_incomplete_market_window_is_excluded_without_model_judgment(self) -> None:
        claim = {"claim_id": "v-c001", "scoreability": "conditional_scoreable"}
        outcome = {"claim_id": "v-c001", "assets": [{
            "status": "available",
            "window_24h": {"complete": False},
            "window_48h": {"complete": False},
        }]}
        score = deterministic_exclusion(claim, outcome)
        self.assertIsNotNone(score)
        self.assertEqual(score.result, "insufficient_data")
        self.assertFalse(score.counts_in_final_score)
        self.assertEqual(score.data_sufficiency, "partial")

    def test_counted_score_requires_complete_market_window(self) -> None:
        claim = {
            "claim_id": "v-c001",
            "scoreability": "scoreable",
        }
        parsed = ModelVideoScoring(
            video_id="v",
            scores=[ClaimScoreCandidate(
                claim_id="v-c001",
                result="correct",
                score=1,
                counts_in_final_score=True,
                trigger_status="not_applicable",
                data_sufficiency="sufficient",
                evidence_summary="No complete window exists.",
                reasoning="This must be rejected by application validation.",
                evaluation_window="24h",
                scoring_confidence=0.8,
            )],
            scoring_notes=[],
        )
        outcomes = {"v-c001": {"claim_id": "v-c001", "assets": [{
            "status": "available",
            "window_24h": {"complete": False},
            "window_48h": {"complete": False},
        }]}}
        with self.assertRaises(ScoringContractError):
            validate_video_scoring(parsed, "v", [claim], outcomes)

    def test_counted_conditional_claim_requires_triggered_status(self) -> None:
        claim = {"claim_id": "v-c001", "scoreability": "conditional_scoreable"}
        parsed = ModelVideoScoring(video_id="v", scores=[ClaimScoreCandidate(
            claim_id="v-c001", result="correct", score=1, counts_in_final_score=True,
            trigger_status="unclear", data_sufficiency="sufficient",
            evidence_summary="Complete data exists.", reasoning="Trigger was not established.",
            evaluation_window="24h", scoring_confidence=0.8,
        )], scoring_notes=[])
        outcomes = {"v-c001": {"assets": [{
            "status": "available", "window_24h": {"complete": True}, "window_48h": {"complete": False},
        }]}}
        with self.assertRaises(ScoringContractError):
            validate_video_scoring(parsed, "v", [claim], outcomes)

    def test_direct_claim_cannot_be_not_triggered(self) -> None:
        claim = {"claim_id": "v-c001", "scoreability": "scoreable"}
        parsed = ModelVideoScoring(video_id="v", scores=[ClaimScoreCandidate(
            claim_id="v-c001", result="not_triggered", score=0, counts_in_final_score=False,
            trigger_status="not_triggered", data_sufficiency="sufficient",
            evidence_summary="No trigger.", reasoning="Direct claim has no trigger.",
            evaluation_window="24h", scoring_confidence=0.8,
        )], scoring_notes=[])
        with self.assertRaises(ScoringContractError):
            validate_video_scoring(parsed, "v", [claim], {"v-c001": {"assets": []}})

    def test_multi_asset_claim_requires_complete_data_for_every_asset(self) -> None:
        claim = {"claim_id": "v-c001", "scoreability": "scoreable"}
        outcome = {"claim_id": "v-c001", "assets": [
            {"status": "available", "window_24h": {"complete": True}, "window_48h": {"complete": False}},
            {"status": "unsupported_asset"},
        ]}
        score = deterministic_exclusion(claim, outcome)
        self.assertIsNotNone(score)
        self.assertEqual(score.result, "insufficient_data")

    def test_mixed_complete_windows_cannot_be_combined_across_assets(self) -> None:
        outcome = {"assets": [
            {
                "status": "available",
                "window_24h": {"complete": True},
                "window_48h": {"complete": False},
            },
            {
                "status": "available",
                "window_24h": {"complete": False},
                "window_48h": {"complete": True},
            },
        ]}
        self.assertFalse(outcome_supports_window(outcome, "24h"))
        self.assertFalse(outcome_supports_window(outcome, "48h"))
        score = deterministic_exclusion(
            {"claim_id": "v-c001", "scoreability": "scoreable", "time_horizon": None},
            outcome,
        )
        self.assertEqual(score.result, "insufficient_data")
        self.assertEqual(score.evaluation_window, "24h")

    def test_counted_result_must_use_normalized_claim_window(self) -> None:
        claim = {
            "claim_id": "v-c001",
            "scoreability": "scoreable",
            "time_horizon": "48 hours",
            "normalized_horizon_hours": 48,
        }
        self.assertEqual(required_evaluation_window(claim), "48h")
        parsed = ModelVideoScoring(video_id="v", scores=[ClaimScoreCandidate(
            claim_id="v-c001", result="correct", score=1, counts_in_final_score=True,
            trigger_status="not_applicable", data_sufficiency="sufficient",
            evidence_summary="Complete values.", reasoning="Wrong selected contract window.",
            evaluation_window="24h", scoring_confidence=0.8,
        )], scoring_notes=[])
        outcomes = {"v-c001": {"assets": [{
            "status": "available",
            "window_24h": {"complete": True},
            "window_48h": {"complete": True},
        }]}}
        with self.assertRaisesRegex(ScoringContractError, "machine-selected"):
            validate_video_scoring(parsed, "v", [claim], outcomes)

    def test_not_triggered_requires_sufficient_complete_selected_window(self) -> None:
        claim = {
            "claim_id": "v-c001",
            "scoreability": "conditional_scoreable",
            "time_horizon": None,
        }
        parsed = ModelVideoScoring(video_id="v", scores=[ClaimScoreCandidate(
            claim_id="v-c001", result="not_triggered", score=0, counts_in_final_score=False,
            trigger_status="not_triggered", data_sufficiency="sufficient",
            evidence_summary="Trigger not seen.", reasoning="Window was incomplete.",
            evaluation_window="24h", scoring_confidence=0.8,
        )], scoring_notes=[])
        outcomes = {"v-c001": {"assets": [{
            "status": "available",
            "window_24h": {"complete": False},
            "window_48h": {"complete": True},
        }]}}
        with self.assertRaisesRegex(ScoringContractError, "selected complete window"):
            validate_video_scoring(parsed, "v", [claim], outcomes)

        parsed.scores[0].data_sufficiency = "partial"
        outcomes["v-c001"]["assets"][0]["window_24h"]["complete"] = True
        with self.assertRaisesRegex(ScoringContractError, "sufficient trigger evidence"):
            validate_video_scoring(parsed, "v", [claim], outcomes)

    def test_direct_claim_never_uses_triggered_status(self) -> None:
        claim = {"claim_id": "v-c001", "scoreability": "scoreable", "time_horizon": None}
        parsed = ModelVideoScoring(video_id="v", scores=[ClaimScoreCandidate(
            claim_id="v-c001", result="correct", score=1, counts_in_final_score=True,
            trigger_status="triggered", data_sufficiency="sufficient",
            evidence_summary="Complete values.", reasoning="Direct claim.",
            evaluation_window="24h", scoring_confidence=0.8,
        )], scoring_notes=[])
        outcomes = {"v-c001": {"assets": [{
            "status": "available", "window_24h": {"complete": True}, "window_48h": {"complete": True},
        }]}}
        with self.assertRaisesRegex(ScoringContractError, "Direct claims"):
            validate_video_scoring(parsed, "v", [claim], outcomes)

    def test_unsupported_explicit_horizon_is_deterministically_excluded(self) -> None:
        claim = {
            "claim_id": "v-c001",
            "scoreability": "scoreable",
            "time_horizon": "next week",
            "normalized_horizon_hours": None,
        }
        outcome = {"assets": [{
            "status": "available", "window_24h": {"complete": True}, "window_48h": {"complete": True},
        }]}
        score = deterministic_exclusion(claim, outcome)
        self.assertEqual(score.result, "not_scoreable")
        self.assertFalse(score.counts_in_final_score)
        self.assertIsNone(score.evaluation_window)

    def test_timestamp_only_legacy_score_artifact_is_not_blessed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(_env_file=None, WORKSPACE_DIR=Path(tmp))
            for directory in (settings.pack_dir, settings.claims_dir, settings.outcomes_dir, settings.scores_dir):
                directory.mkdir(parents=True, exist_ok=True)
            video = {
                "video_id": "v",
                "upload_date": "20260601",
                "published_at_utc": "2026-06-01T00:00:00+00:00",
                "category": "crypto",
                "title": "Synthetic fixture",
                "transcript_txt": "raw/v.txt",
                "transcript_sha256": "transcript-hash",
            }
            (settings.pack_dir / "manifest.json").write_text(json.dumps({
                "collection_id": "collection", "videos": [video],
            }), encoding="utf-8")
            (settings.claims_dir / "extraction_run.json").write_text(json.dumps({
                "collection_id": "collection",
                "status": "complete",
                "schema_version": CLAIM_SCHEMA_VERSION,
                "evidence_policy": EVIDENCE_POLICY,
                "model": settings.openai_claim_model,
                "reasoning_effort": settings.openai_claim_reasoning_effort,
                "prompt_sha256": sha256_text(CLAIM_PROMPT_PATH.read_text(encoding="utf-8")),
            }), encoding="utf-8")
            claim = {
                "claim_id": "v-c001", "claim_text": "BTC rises", "scoreability": "scoreable",
                "time_horizon": None, "normalized_horizon_hours": None,
            }
            (settings.claims_dir / "v.claims.json").write_text(json.dumps({
                "collection_id": "collection", "video_id": "v",
                "transcript_sha256": "transcript-hash",
                "schema_version": CLAIM_SCHEMA_VERSION,
                "evidence_policy": EVIDENCE_POLICY,
                "requested_model": settings.openai_claim_model,
                "reasoning_effort": settings.openai_claim_reasoning_effort,
                "prompt_sha256": sha256_text(CLAIM_PROMPT_PATH.read_text(encoding="utf-8")),
                "claims": [claim],
            }), encoding="utf-8")
            outcome = {"claim_id": "v-c001", "assets": [{
                "status": "available", "window_24h": {"complete": True}, "window_48h": {"complete": True},
            }]}
            (settings.outcomes_dir / "claim_outcomes.json").write_text(json.dumps({
                "collection_id": "collection", "created_at_utc": "2026-06-02T00:00:00+00:00",
                "claims": [outcome],
            }), encoding="utf-8")
            legacy_score = {
                "schema_version": SCORING_SCHEMA_VERSION,
                "scoring_policy": SCORING_POLICY,
                "collection_id": "collection",
                "created_at_utc": "2099-01-01T00:00:00+00:00",
                "video_id": "v",
                "requested_model": settings.openai_scoring_model,
                "reasoning_effort": settings.openai_scoring_reasoning_effort,
                "prompt_sha256": sha256_text(PROMPT_PATH.read_text(encoding="utf-8")),
                "scores": [],
            }
            (settings.scores_dir / "v.scores.json").write_text(json.dumps(legacy_score), encoding="utf-8")

            parsed = ModelVideoScoring(video_id="v", scores=[ClaimScoreCandidate(
                claim_id="v-c001", result="correct", score=1, counts_in_final_score=True,
                trigger_status="not_applicable", data_sufficiency="sufficient",
                evidence_summary="Complete fixture window.", reasoning="Fixture rose.",
                evaluation_window="24h", scoring_confidence=0.8,
            )], scoring_notes=[])

            class FakeResponses:
                def __init__(self) -> None:
                    self.calls = 0

                def parse(self, **kwargs):
                    self.calls += 1
                    return SimpleNamespace(
                        id="response", model=settings.openai_scoring_model, output_parsed=parsed,
                        usage=SimpleNamespace(
                            input_tokens=10, output_tokens=5, total_tokens=15,
                            input_tokens_details=SimpleNamespace(cached_tokens=0),
                        ),
                    )

            responses = FakeResponses()
            run_scoring(settings, client=SimpleNamespace(responses=responses))
            self.assertEqual(responses.calls, 1)


if __name__ == "__main__":
    unittest.main()
