"""Phase 26D — kernel signal-drop trace tests (offline; no MT5)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.phase26d_kernel_signal_trace import (
    PHASE26D_JSON,
    _classify_root_cause,
    run_phase26d_collection,
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


class TestPhase26DClassification(unittest.TestCase):
    def test_riskgate_multiple_reasons_is_h(self) -> None:
        cls, site, fix = _classify_root_cause(
            {
                "candidates": 19,
                "signal_stage_signal": 19,
                "risk_stage_reached": 19,
                "risk_allowed": 0,
                "journal_appended": 0,
                "risk_rejection_reasons": {
                    "lot too small": 3,
                    "meta-labeler rejected (p=0.14)": 10,
                    "ATR percentile too high (97>96)": 6,
                },
            }
        )
        self.assertTrue(cls.startswith("H"))
        self.assertIn("BacktestRiskGate", site)
        self.assertTrue(fix)

    def test_upstream_drop_is_e(self) -> None:
        cls, site, _ = _classify_root_cause(
            {"candidates": 5, "signal_stage_signal": 0, "risk_stage_reached": 0}
        )
        self.assertTrue(cls.startswith("E"))
        self.assertEqual(site, "SignalStage")


class TestPhase26DOffline(unittest.TestCase):
    def test_deterministic_offline_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data" / "backtest"
            data_dir.mkdir(parents=True)
            df = _synthetic_m5(450)
            df.to_parquet(data_dir / "XAUUSD_M5_183d.parquet")

            with patch(
                "tradingbot.backtest.phase26d_kernel_signal_trace._enrich_frame",
                return_value=df,
            ):
                r1 = run_phase26d_collection(root)
                r2 = run_phase26d_collection(root)

            self.assertEqual(r1.get("status"), r2.get("status"))
            self.assertTrue((root / PHASE26D_JSON).is_file())
            self.assertFalse(r1["safety"]["MT5_STARTED"])
            self.assertFalse(r1["safety"]["ENV_ACCESSED"])
            self.assertFalse(r1["safety"]["SYMBOL_SELECT"])
            self.assertFalse(r1["safety"]["DATASETS_MUTATED"])
            self.assertFalse(r1["safety"]["STRATEGY_CHANGED"])
            self.assertFalse(r1["safety"]["RISKGATE_CHANGED"])
            self.assertIn("root_cause_classification", r1)

    def test_real_dataset_trace_when_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        parquet = root / "data" / "backtest" / "XAUUSD_M5_183d.parquet"
        if not parquet.is_file():
            self.skipTest("XAUUSD parquet not available")

        report = run_phase26d_collection(root)
        self.assertIn(report["status"], ("PASS", "PASS_WITH_DEFERRAL", "FAIL"))
        self.assertEqual(report["phase26c_context"]["candidates_expected"], 19)
        prop = report.get("propagation_counts") or {}
        if prop.get("candidates", 0) >= 19:
            self.assertEqual(prop.get("signal_stage_signal"), 19)
            self.assertEqual(prop.get("risk_stage_reached"), 19)
            self.assertEqual(prop.get("risk_allowed"), 0)
            self.assertTrue(report["root_cause_classification"].startswith(("F", "H")))
        artifact = root / PHASE26D_JSON
        self.assertTrue(artifact.is_file())
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "26D")


if __name__ == "__main__":
    unittest.main()
