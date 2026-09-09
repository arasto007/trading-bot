"""Phase 26C — lightweight zero-signal audit tests (offline; no MT5)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.phase26c_zero_signal_audit import (
    PHASE26C_JSON,
    _classify_root_cause,
    run_phase26c_zero_signal_audit,
)


def _synthetic_m5(bars: int = 400) -> pd.DataFrame:
    idx = pd.date_range("2026-07-28 00:00", periods=bars, freq="5min", tz="UTC")
    close = pd.Series([2400.0 + (i % 80) * 0.1 for i in range(bars)], index=idx)
    return pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100.0,
        },
        index=idx,
    )


class TestPhase26CClassification(unittest.TestCase):
    def test_empty_ny_session_is_class_c(self) -> None:
        cls, gate = _classify_root_cause(
            {"ny_session_bars": 0, "asian_range_valid": 0, "sweep_detected": 0,
             "reclaim_detected": 0, "setup_ok_pre_hardening": 0, "evaluate_gold_setup_pass": 0,
             "confidence_pass": 0, "market_filter_pass_on_candidates": 0},
            {"bars_in_ny_window": 0},
        )
        self.assertTrue(cls.startswith("C"))
        self.assertEqual(gate, "ny_session_window_empty")

    def test_zero_sweep_is_not_strategy_failure_label(self) -> None:
        cls, gate = _classify_root_cause(
            {"ny_session_bars": 10, "asian_range_valid": 10, "sweep_detected": 0,
             "reclaim_detected": 0, "setup_ok_pre_hardening": 0, "evaluate_gold_setup_pass": 0,
             "confidence_pass": 0, "market_filter_pass_on_candidates": 0},
            {"bars_in_ny_window": 10},
        )
        self.assertTrue(cls.startswith("A"))
        self.assertEqual(gate, "sweep_detection")


class TestPhase26COffline(unittest.TestCase):
    def test_deterministic_offline_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data" / "backtest"
            data_dir.mkdir(parents=True)
            df = _synthetic_m5(450)
            df.to_parquet(data_dir / "XAUUSD_M5_183d.parquet")

            with patch(
                "tradingbot.backtest.phase26c_zero_signal_audit._enrich_frame",
                return_value=df,
            ):
                r1 = run_phase26c_zero_signal_audit(root, bars=400, warmup=50)
                r2 = run_phase26c_zero_signal_audit(root, bars=400, warmup=50)

            self.assertEqual(r1["gate_counts"], r2["gate_counts"])
            self.assertTrue((root / PHASE26C_JSON).is_file())
            self.assertFalse(r1["safety"]["MT5_STARTED"])
            self.assertFalse(r1["safety"]["ENV_ACCESSED"])
            self.assertFalse(r1["safety"]["SYMBOL_SELECT"])
            self.assertFalse(r1["safety"]["DATASETS_MUTATED"])
            self.assertFalse(r1["safety"]["CONFIGURATION_MUTATED"])
            self.assertIn("root_cause_classification", r1)
            self.assertNotIn("strategy failure", r1["root_cause"]["summary"].lower())

    def test_gate_counts_internally_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data" / "backtest"
            data_dir.mkdir(parents=True)
            _synthetic_m5(450).to_parquet(data_dir / "XAUUSD_M5_183d.parquet")

            with patch(
                "tradingbot.backtest.phase26c_zero_signal_audit._enrich_frame",
                side_effect=lambda df: df,
            ):
                report = run_phase26c_zero_signal_audit(root, bars=400, warmup=50)

            gc = report["gate_counts"]
            self.assertLessEqual(gc["reclaim_detected"], gc["sweep_detected"])
            self.assertLessEqual(gc["setup_ok_pre_hardening"], gc["reclaim_detected"])
            risk_entries = next(
                g["count"] for g in report["signal_gate_pipeline"] if g["gate"] == "risk_gate_entries_phase26b"
            )
            self.assertEqual(risk_entries, 0)


class TestPhase26CArtifactShape(unittest.TestCase):
    def test_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data" / "backtest"
            data_dir.mkdir(parents=True)
            _synthetic_m5(200).to_parquet(data_dir / "XAUUSD_M5_183d.parquet")
            with patch(
                "tradingbot.backtest.phase26c_zero_signal_audit._enrich_frame",
                side_effect=lambda df: df,
            ):
                report = run_phase26c_zero_signal_audit(root, bars=180, warmup=30)
            for key in (
                "signal_gate_pipeline",
                "session_timezone_audit",
                "meta_labeler_audit",
                "configuration_comparison",
                "final_decision",
            ):
                self.assertIn(key, report)
            self.assertEqual(report["final_decision"], "PASS_WITH_DEFERRAL")


if __name__ == "__main__":
    unittest.main()
