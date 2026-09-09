"""Phase 31 — event independence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
)
from tradingbot.backtest.phase31_event_independence import (
    BLOCKED,
    EVENT_CONSTRUCTION,
    PHASE,
    PHASE31_JSON,
    PHASE31_MD,
    REQUIRED_ARTIFACT_KEYS,
    mechanical_event_key,
    run_phase31_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase31_collection(Path(__file__).resolve().parents[1])


class TestPhase31EventIndependence(unittest.TestCase):
    def test_frozen_tape_and_mechanical_events(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE31_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["parameters_searched"])
        self.assertFalse(payload["strategy_changed"])
        self.assertEqual(payload["event_definition"]["name"], EVENT_CONSTRUCTION["name"])
        self.assertTrue(payload["event_definition"]["not_invented_to_improve_statistics"])
        self.assertFalse(payload["event_definition"]["phase28_4_heuristic"]["used_as_official_event"])
        metrics = payload["event_metrics"]
        self.assertEqual(metrics["signal_count"], 24)
        self.assertLess(metrics["event_count"], 24)
        self.assertLessEqual(metrics["event_count"], metrics["phase28_4_heuristic_event_count"])
        self.assertGreaterEqual(metrics["signals_per_event"]["mean"], 2.0)
        rows = payload["signal_classifications"]
        self.assertEqual(len(rows), 24)
        for key in (
            "unique_event",
            "repeated_signal_within_same_event",
            "same_direction_reentry",
            "opposite_direction_signal",
            "same_sweep",
            "same_ny_session",
            "same_day",
            "overlapping_holding_period",
        ):
            self.assertIn(key, rows[0])
        unique = sum(1 for r in rows if r["unique_event"])
        self.assertEqual(unique, metrics["event_count"])
        self.assertEqual(sum(1 for r in rows if r["repeated_signal_within_same_event"]), 24 - unique)

    def test_concentration_bootstrap_and_high_dependence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE31_JSON).read_text(encoding="utf-8"))
        conc = payload["concentration"]
        self.assertIn("top_1_event", conc)
        self.assertIn("top_2_events", conc)
        self.assertIn("top_5_events", conc)
        self.assertIn("top_10pct_events", conc)
        self.assertGreater(conc["largest_cluster_signal_share"], 0.0)
        self.assertTrue(payload["dependence"]["treating_signals_independently_exaggerates_evidence"])
        self.assertTrue(payload["dependence"]["not_a_strategy_failure"])
        self.assertGreaterEqual(payload["dependence"]["same_stop_event"]["groups_ge_3"], 1)
        boot = payload["bootstrap"]
        self.assertIn("signal_level", boot)
        self.assertIn("event_level", boot)
        self.assertFalse(boot["signal_level"]["independent_evidence"])
        self.assertTrue(boot["do_not_present_signal_level_as_independent"])
        self.assertEqual(boot["signal_level"]["n"], 24)
        self.assertEqual(boot["event_level"]["n"], payload["event_metrics"]["event_count"])
        self.assertEqual(payload["dependence_grade"]["grade"], "HIGH_DEPENDENCE")
        self.assertGreaterEqual(payload["dependence_grade"]["hit_count"], 2)
        self.assertTrue(payload["dependence_grade"]["not_a_strategy_failure"])
        key = mechanical_event_key(
            {
                "timestamp": "2026-08-20 15:35:00+00:00",
                "asian_high": 4521.12,
                "asian_low": 4477.81,
                "side": "SELL",
            }
        )
        self.assertEqual(key[0], "2026-08-20")
        self.assertEqual(key[3], "SELL")

    def test_reproducible_no_phase_32(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE31_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["conclusion"]["verdict"], "HIGH_DEPENDENCE")
        self.assertTrue(payload["conclusion"]["not_a_strategy_failure"])
        self.assertFalse(payload["conclusion"]["edge_supported"])
        self.assertFalse(payload["conclusion"]["no_edge_supported"])
        self.assertFalse(payload["conclusion"]["signal_level_independent_evidence"])
        self.assertTrue(payload["reproducibility"]["passes_match"])
        self.assertEqual(payload["reproducibility"]["passes"], 2)
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_32_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase31_event_independence.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE31_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 31", md)
        self.assertIn("DO NOT START PHASE 32", md)
        self.assertIn("HIGH_DEPENDENCE", md)
        self.assertNotIn("phase32_", src.lower())
