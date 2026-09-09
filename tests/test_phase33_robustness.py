"""Phase 33 — robustness diagnostic tests."""

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
from tradingbot.backtest.phase33_robustness import (
    BLOCKED,
    PHASE,
    PHASE33_JSON,
    PHASE33_MD,
    REQUIRED_ARTIFACT_KEYS,
    RR_OFFSETS,
    SL_DISTANCE_MULTIPLIERS,
    run_phase33_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase33_collection(Path(__file__).resolve().parents[1])


class TestPhase33Robustness(unittest.TestCase):
    def test_baseline_and_predeclared_diagnostics(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE33_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["parameters_searched"])
        self.assertFalse(payload["strategy_changed"])
        self.assertFalse(payload["rr_changed"])
        self.assertTrue(payload["perturbation_spec"]["not_a_search"])
        self.assertEqual(tuple(payload["perturbation_spec"]["sl_distance_multipliers"]), SL_DISTANCE_MULTIPLIERS)
        self.assertEqual(tuple(payload["perturbation_spec"]["rr_offsets"]), RR_OFFSETS)
        self.assertEqual(payload["baseline"]["n"], 24)
        self.assertEqual(payload["baseline"]["unique_events"], 6)
        self.assertEqual(payload["baseline"]["phase32_verdict"], "INSUFFICIENT_SAMPLE")
        entry = payload["entry_robustness"]
        self.assertEqual(entry["class"], "ANALYTICAL_COUNTERFACTUAL")
        self.assertTrue(entry["production_entry_unchanged"])
        for key in (
            "official_close",
            "next_bar_open",
            "first_eligible_reclaim_close",
            "small_execution_displacement",
        ):
            self.assertIn(key, entry)
            self.assertEqual(entry[key]["n"], 24)
        self.assertTrue(payload["sl_robustness"]["not_a_parameter_search"])
        self.assertTrue(payload["tp_rr_robustness"]["not_a_parameter_search"])
        self.assertIn("sl_distance_x0.90", payload["sl_robustness"]["perturbations"])
        self.assertIn("sl_distance_x1.10", payload["sl_robustness"]["perturbations"])
        self.assertEqual(len(payload["sl_robustness"]["perturbations"]), 2)
        self.assertEqual(len(payload["tp_rr_robustness"]["perturbations"]), 2)

    def test_costs_quality_events_labeled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE33_JSON).read_text(encoding="utf-8"))
        cost = payload["cost_shocks"]
        self.assertEqual(cost["components"]["spread"], "MODELED_PROXY")
        self.assertEqual(cost["components"]["slippage"], "MODELED_PROXY")
        self.assertEqual(cost["components"]["commission"], "UNKNOWN")
        self.assertFalse(cost["components"]["observed_broker_costs"])
        for name in ("baseline", "moderate", "high_plausible"):
            self.assertEqual(cost["books"][name]["label"], "MODELED")
            self.assertTrue(cost["books"][name]["not_realized"])
        self.assertFalse(payload["signal_quality"]["thresholds_tuned"])
        self.assertTrue(any(s["insufficient_slice"] for s in payload["time_robustness"]["weekday"]))
        self.assertEqual(payload["event_robustness"]["n_events"], 6)
        self.assertTrue(payload["event_robustness"]["not_optimized"])
        self.assertFalse(payload["lookahead"]["precedence_changed"])

    def test_insufficient_sample_no_phase_34(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE33_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["conclusion"]["verdict"], "INSUFFICIENT_SAMPLE")
        self.assertFalse(payload["conclusion"]["edge_supported"])
        self.assertFalse(payload["conclusion"]["robustness_proven"])
        self.assertTrue(payload["reproducibility"]["passes_match"])
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_34_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase33_robustness.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE33_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 33", md)
        self.assertIn("DO NOT START PHASE 34", md)
        self.assertIn("INSUFFICIENT_SAMPLE", md)
        self.assertNotIn("phase34_", src.lower())
