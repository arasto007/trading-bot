"""Phase 28.2 — chronological walk-forward tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    PHASE280_BASELINE_JSON,
)
from tradingbot.backtest.phase28_2_walk_forward import (
    BLOCKED,
    FOLD_NAMES,
    PHASE,
    PHASE282_JSON,
    PHASE282_MD,
    REQUIRED_ARTIFACT_KEYS,
    classify_stability,
    chronological_index_splits,
    fold_for_index,
    run_phase28_2_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase28_2_collection(Path(__file__).resolve().parents[1])


class TestPhase282WalkForward(unittest.TestCase):
    def test_split_is_chronological_60_20_20(self) -> None:
        splits = chronological_index_splits(3000)
        self.assertEqual(splits["TRAIN"]["start_index"], 0)
        self.assertEqual(splits["TRAIN"]["end_index"], 1800)
        self.assertEqual(splits["VALIDATION"]["start_index"], 1800)
        self.assertEqual(splits["VALIDATION"]["end_index"], 2400)
        self.assertEqual(splits["OOS"]["start_index"], 2400)
        self.assertEqual(splits["OOS"]["end_index"], 3000)
        self.assertEqual(fold_for_index(0, splits), "TRAIN")
        self.assertEqual(fold_for_index(1799, splits), "TRAIN")
        self.assertEqual(fold_for_index(1800, splits), "VALIDATION")
        self.assertEqual(fold_for_index(2399, splits), "VALIDATION")
        self.assertEqual(fold_for_index(2400, splits), "OOS")
        self.assertEqual(fold_for_index(2999, splits), "OOS")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE282_JSON).read_text(encoding="utf-8"))
        folds = payload["splits"]["folds"]
        self.assertLess(folds["TRAIN"]["end"], folds["VALIDATION"]["start"])
        self.assertLess(folds["VALIDATION"]["end"], folds["OOS"]["start"])
        self.assertEqual(payload["splits"]["fractions"], {"TRAIN": 0.6, "VALIDATION": 0.2, "OOS": 0.2})

    def test_approved_dataset_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE282_JSON).read_text(encoding="utf-8"))
        p28 = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["approved_dataset"]["path"], CANONICAL_PARQUET)
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(payload["dataset_fingerprint"], p28["dataset_fingerprint"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertEqual(payload["research_configuration"]["dataset_symbol_map"], {})
        self.assertTrue(payload["research_configuration"]["identical_across_folds"])
        self.assertFalse(payload["datasets_changed"])

    def test_no_lookahead_and_no_optimization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE282_JSON).read_text(encoding="utf-8"))
        look = payload["lookahead"]
        self.assertTrue(look["official_results_closed_bars_only"])
        self.assertFalse(look["features_use_future_candles"])
        self.assertTrue(look["future_fold_not_used_for_past_signals"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertTrue(payload["train_validation_descriptive_only"])
        self.assertFalse(payload["monte_carlo"])
        self.assertFalse(payload["strategy_changed"])
        self.assertFalse(payload["riskgate_changed"])

    def test_raw_executable_and_degradation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE282_JSON).read_text(encoding="utf-8"))
        raw = payload["raw_signal"]["folds"]
        exe = payload["executable"]["folds"]
        for name in FOLD_NAMES:
            self.assertIn(name, raw)
            self.assertIn(name, exe)
            for key in (
                "total_trades",
                "win_rate",
                "expectancy_R",
                "profit_factor",
                "max_drawdown_R",
                "trades_per_calendar_day",
                "BUY",
                "SELL",
                "session_distribution",
            ):
                self.assertIn(key, raw[name])
            self.assertEqual(exe[name]["candidates"], raw[name]["setups"])
            self.assertEqual(exe[name]["allowed"] + exe[name]["rejected"], exe[name]["candidates"])
        self.assertEqual(sum(raw[n]["setups"] for n in FOLD_NAMES), payload["raw_signal"]["setups_total"])
        self.assertIn("TRAIN_TO_VALIDATION", payload["degradation"])
        self.assertIn("VALIDATION_TO_OOS", payload["degradation"])
        self.assertIn("TRAIN_TO_OOS", payload["degradation"])
        self.assertEqual(payload["executable"]["allowed_total"], 0)
        self.assertEqual(payload["stability"]["classification"], "INSUFFICIENT_SAMPLE")
        empty = classify_stability(
            {
                "TRAIN": {"total_trades": 2, "expectancy_R": 0.1},
                "VALIDATION": {"total_trades": 1, "expectancy_R": 0.0},
                "OOS": {"total_trades": 1, "expectancy_R": -0.2},
            }
        )
        self.assertEqual(empty["classification"], "INSUFFICIENT_SAMPLE")

    def test_gate_and_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE282_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_28_3_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase28_2_walk_forward.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE282_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 28.2", md)
        self.assertIn("DO NOT START PHASE 28.3", md)
        self.assertIn("descriptive only", md.lower())
        self.assertLess(payload["splits"]["folds"]["TRAIN"]["end"], payload["splits"]["folds"]["OOS"]["start"])
