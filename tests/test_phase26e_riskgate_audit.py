"""Phase 26E — RiskGate rejection audit tests (offline; no MT5)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.phase26e_riskgate_audit import (
    PHASE26E_JSON,
    RISKGATE_EVAL_ORDER,
    _classify_lot_root,
    _classify_overall,
    _first_rejection_gate,
    run_phase26e_collection,
)


class TestPhase26EHelpers(unittest.TestCase):
    def test_first_rejection_atr(self) -> None:
        gate = _first_rejection_gate(final_reason="ATR percentile too high (98>95)")
        self.assertEqual(gate, "check_market_filters")

    def test_lot_root_config_mismatch(self) -> None:
        cls = _classify_lot_root(
            [{"final_riskgate_reason": "lot too small", "lot_sizing": {"economics_found_xauusd": False}}]
        )
        self.assertEqual(cls, "CONFIG/DATA MISMATCH")

    def test_overall_multiple_causes(self) -> None:
        cls = _classify_overall(
            "CONFIG/DATA MISMATCH",
            "LEGITIMATE CONFIGURED BEHAVIOR",
            "LEGITIMATE CONFIGURED BEHAVIOR",
            lot_n=3,
            meta_n=10,
            atr_n=6,
        )
        self.assertTrue(cls.startswith("F"))

    def test_eval_order_includes_market_before_meta(self) -> None:
        i_mf = RISKGATE_EVAL_ORDER.index("check_market_filters")
        i_meta = RISKGATE_EVAL_ORDER.index("meta_labeler")
        i_lot = RISKGATE_EVAL_ORDER.index("lot_sizing")
        self.assertLess(i_mf, i_meta)
        self.assertLess(i_meta, i_lot)


class TestPhase26EOffline(unittest.TestCase):
    def test_missing_26d_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                run_phase26e_collection(tmp)

    def test_real_audit_when_artifacts_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        d26 = root / "logs" / "phase26d_kernel_signal_trace.json"
        parquet = root / "data" / "backtest" / "XAUUSD_M5_183d.parquet"
        if not d26.is_file() or not parquet.is_file():
            self.skipTest("Phase 26D artifact or parquet missing")

        report = run_phase26e_collection(root)
        self.assertIn(report["status"], ("PASS", "PASS_WITH_DEFERRAL"))
        self.assertEqual(report["candidate_count"], 19)
        self.assertEqual(len(report["decision_table"]), 19)
        self.assertFalse(report["safety"]["MT5_STARTED"])
        self.assertFalse(report["safety"]["ENV_ACCESSED"])
        self.assertTrue((root / PHASE26E_JSON).is_file())
        lot = report["lot_sizing_audit"]
        self.assertEqual(lot["count"], 3)
        self.assertTrue(lot["resolve_xauusd_returns_none"])
        meta = report["meta_labeler_audit"]
        self.assertEqual(meta["count"], 10)
        atr = report["atr_filter_audit"]
        self.assertEqual(atr["count"], 6)
        payload = json.loads((root / PHASE26E_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "26E")


if __name__ == "__main__":
    unittest.main()
