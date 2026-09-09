"""Phase 34 — statistical validation tests."""

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
from tradingbot.backtest.phase34_statistical_validation import (
    BLOCKED,
    N_PATHS,
    PHASE,
    PHASE34_JSON,
    PHASE34_MD,
    REQUIRED_ARTIFACT_KEYS,
    RNG_SEED,
    run_phase34_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase34_collection(Path(__file__).resolve().parents[1])


class TestPhase34StatisticalValidation(unittest.TestCase):
    def test_two_units_and_frozen_tape(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE34_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["parameters_searched"])
        self.assertEqual(payload["units"]["signal_level"]["n"], 24)
        self.assertFalse(payload["units"]["signal_level"]["independent_evidence"])
        self.assertEqual(payload["units"]["event_level"]["n"], 6)
        self.assertTrue(payload["units"]["event_level"]["independent_evidence"])
        self.assertTrue(payload["units"]["event_level"]["still_insufficient"])
        self.assertFalse(payload["bootstrap"]["signal_level"]["independent_evidence"])
        self.assertTrue(payload["bootstrap"]["event_level"]["independent_evidence"])
        self.assertEqual(payload["bootstrap"]["seed"], RNG_SEED)
        self.assertEqual(payload["bootstrap"]["n_paths"], N_PATHS)
        for unit in ("signal_level", "event_level"):
            boot = payload["bootstrap"][unit]["bootstrap"]
            for key in ("expectancy_R", "mean_R", "median_R", "win_rate", "profit_factor", "max_drawdown_R", "longest_losing_streak"):
                self.assertIn(key, boot)
                self.assertIn("p5", boot[key])
                self.assertIn("p95", boot[key])

    def test_monte_carlo_null_and_multiple_testing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE34_JSON).read_text(encoding="utf-8"))
        mc = payload["monte_carlo"]
        self.assertEqual(mc["seed"], RNG_SEED)
        self.assertEqual(mc["n_paths"], N_PATHS)
        self.assertFalse(mc["ohlc_rewalked"])
        self.assertFalse(mc["broker_margin_ruin_model"])
        self.assertTrue(mc["not_broker_margin_ruin"])
        self.assertIn("prob_dd_ge_10R", mc["event_level_bootstrap"])
        self.assertIn("prob_final_R_negative", mc["event_level_shuffle"])
        null = payload["null_checks"]["event_level"]["sign_flip_null"]
        self.assertTrue(null["not_a_classical_p_value"])
        self.assertTrue(null["do_not_interpret_as_significance"])
        mt = payload["multiple_testing"]
        self.assertFalse(mt["parameter_search_in_phases_30_to_33"])
        self.assertFalse(mt["retroactive_optimization"])
        self.assertTrue(mt["sequential_research_phases"])
        self.assertFalse(mt["family_wise_error_controlled"])
        self.assertFalse(mt["pre_registered_primary_endpoint"])
        self.assertEqual(payload["phase32_verdict"], "INSUFFICIENT_SAMPLE")

    def test_insufficient_sample_no_phase_35(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE34_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["conclusion"]["verdict"], "INSUFFICIENT_SAMPLE")
        self.assertFalse(payload["conclusion"]["edge_supported"])
        self.assertFalse(payload["conclusion"]["statistical_significance_claimed"])
        self.assertFalse(payload["conclusion"]["signal_level_is_independent_evidence"])
        self.assertTrue(payload["reproducibility"]["passes_match"])
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_35_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase34_statistical_validation.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE34_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 34", md)
        self.assertIn("DO NOT START PHASE 35", md)
        self.assertIn("INSUFFICIENT_SAMPLE", md)
        self.assertNotIn("phase35_", src.lower())
