"""Phase 32 — chronological walk-forward tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
)
from tradingbot.backtest.phase28_2_walk_forward import FOLD_NAMES, PHASE282_JSON, chronological_index_splits
from tradingbot.backtest.phase32_walk_forward import (
    BLOCKED,
    PHASE,
    PHASE32_JSON,
    PHASE32_MD,
    REQUIRED_ARTIFACT_KEYS,
    rolling_window_decision,
    run_phase32_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase32_collection(Path(__file__).resolve().parents[1])


class TestPhase32WalkForward(unittest.TestCase):
    def test_chronological_frozen_tape_no_optimization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE32_JSON).read_text(encoding="utf-8"))
        p282 = json.loads((root / PHASE282_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["parameters_searched"])
        self.assertFalse(payload["parameters_changed_across_folds"])
        self.assertFalse(payload["random_split"])
        self.assertFalse(payload["history_shuffled"])
        self.assertFalse(payload["folds_dropped"])
        self.assertFalse(payload["dates_changed"])
        self.assertTrue(payload["train_validation_descriptive_only"])
        self.assertTrue(payload["lookahead"]["future_fold_not_used_for_past_signals"])
        self.assertTrue(payload["splits"]["oos_strictly_after_train"])
        splits = chronological_index_splits(3000)
        self.assertEqual(payload["splits"]["recomputed_60_20_20"]["TRAIN"]["end_index"], splits["TRAIN"]["end_index"])
        self.assertEqual(payload["splits"]["recomputed_60_20_20"]["OOS"]["start_index"], splits["OOS"]["start_index"])
        self.assertEqual(payload["folds"]["TRAIN"]["end_index"], payload["folds"]["VALIDATION"]["start_index"])
        self.assertEqual(payload["folds"]["VALIDATION"]["end_index"], payload["folds"]["OOS"]["start_index"])
        self.assertLess(payload["folds"]["TRAIN"]["start_index"], payload["folds"]["OOS"]["start_index"])
        self.assertEqual(
            {n: payload["folds"][n]["setups"] for n in FOLD_NAMES},
            {n: p282["raw_signal"]["folds"][n]["setups"] for n in FOLD_NAMES},
        )

    def test_fold_metrics_events_and_no_rolling(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE32_JSON).read_text(encoding="utf-8"))
        for name in FOLD_NAMES:
            f = payload["folds"][name]
            for key in (
                "bars",
                "days",
                "sessions",
                "events",
                "setups",
                "WR",
                "expectancy",
                "PF",
                "DD",
                "loss_streak",
                "trades_per_day",
                "event_expectancy",
                "event_WR",
                "executable",
                "sufficiency",
            ):
                self.assertIn(key, f)
            self.assertEqual(f["executable"]["allowed"], 0)
            self.assertEqual(f["executable"]["candidates"], f["setups"])
            self.assertTrue(f["insufficient_sample"])
            self.assertLessEqual(f["events"], f["setups"])
        self.assertEqual(payload["folds"]["TRAIN"]["setups"], 4)
        self.assertEqual(payload["folds"]["VALIDATION"]["setups"], 10)
        self.assertEqual(payload["folds"]["OOS"]["setups"], 10)
        self.assertEqual(payload["folds"]["TRAIN"]["events"], 1)
        self.assertEqual(payload["folds"]["VALIDATION"]["events"], 2)
        self.assertEqual(payload["folds"]["OOS"]["events"], 3)
        self.assertFalse(payload["rolling_windows"]["produced"])
        self.assertEqual(payload["rolling_windows"]["windows"], [])
        decision = rolling_window_decision(14.8785)
        self.assertFalse(decision["produced"])
        self.assertLess(14.8785, MIN_CALENDAR_DAYS_FOR_SUFFICIENCY)
        self.assertTrue(payload["stability"]["profitability_is_not_the_only_stability_definition"])
        self.assertEqual(payload["stability"]["classification"], "INSUFFICIENT_SAMPLE")

    def test_insufficient_sample_no_phase_33(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE32_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["conclusion"]["verdict"], "INSUFFICIENT_SAMPLE")
        self.assertFalse(payload["conclusion"]["edge_supported"])
        self.assertFalse(payload["conclusion"]["no_edge_supported"])
        self.assertFalse(payload["conclusion"]["generalization_proven"])
        self.assertTrue(payload["reproducibility"]["passes_match"])
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_33_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase32_walk_forward.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE32_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 32", md)
        self.assertIn("DO NOT START PHASE 33", md)
        self.assertIn("INSUFFICIENT_SAMPLE", md)
        self.assertNotIn("phase33_", src.lower())
