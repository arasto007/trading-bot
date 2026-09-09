"""Phase 26G — RiskGate counterfactual attribution tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase26g_riskgate_counterfactual import (
    PHASE26G_JSON,
    SCENARIOS,
    _blocker_label,
    _classify_zero_trade_driver,
    run_phase26g_collection,
)


class TestPhase26GHelpers(unittest.TestCase):
    def test_blocker_labels(self) -> None:
        self.assertEqual(_blocker_label("lot too small", allowed=False), "LOT")
        self.assertEqual(_blocker_label("meta-labeler rejected (p=0.1)", allowed=False), "META")
        self.assertEqual(_blocker_label("ATR percentile too high (98>95)", allowed=False), "ATR")
        self.assertEqual(_blocker_label(None, allowed=True), "ALLOWED")

    def test_joint_decisive_classification(self) -> None:
        summary = {
            "baseline": {"ALLOWED": 0, "LOT": 3, "META": 10, "ATR": 6, "OTHER": 0},
            "A_no_lot": {"ALLOWED": 3, "LOT": 0, "META": 10, "ATR": 6, "OTHER": 0},
            "B_no_meta": {"ALLOWED": 0, "LOT": 3, "META": 0, "ATR": 6, "OTHER": 10},
            "C_no_atr": {"ALLOWED": 0, "LOT": 3, "META": 10, "ATR": 0, "OTHER": 6},
        }
        code, _ = _classify_zero_trade_driver(summary)
        self.assertTrue(code.startswith("1."))

    def test_scenario_count(self) -> None:
        self.assertEqual(len(SCENARIOS), 7)


class TestPhase26GOffline(unittest.TestCase):
    def test_counterfactual_when_artifacts_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / "logs" / "phase26d_kernel_signal_trace.json").is_file():
            self.skipTest("phase26d artifact missing")
        if not (root / "data" / "backtest" / "XAUUSD_M5_183d.parquet").is_file():
            self.skipTest("parquet missing")

        report = run_phase26g_collection(root)
        self.assertEqual(report["baseline"]["LOT"], 3)
        self.assertEqual(report["baseline"]["META"], 10)
        self.assertEqual(report["baseline"]["ATR"], 6)
        self.assertEqual(report["baseline"]["ALLOWED"], 0)
        self.assertEqual(len(report["attribution_matrix"]), 19)
        self.assertFalse(report["safety"]["PRODUCTION_CODE_CHANGED"])
        self.assertEqual(report["ev_eq_01"], "NOT_PROVEN")
        cf = report["counterfactuals"]
        self.assertEqual(cf["A_no_lot"]["counts"]["ALLOWED"], 3)
        self.assertEqual(cf["C_no_atr"]["counts"]["ALLOWED"], 0)
        self.assertTrue((root / PHASE26G_JSON).is_file())
        payload = json.loads((root / PHASE26G_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "26G")


if __name__ == "__main__":
    unittest.main()
