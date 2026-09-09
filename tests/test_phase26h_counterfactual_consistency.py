"""Phase 26H — counterfactual consistency audit tests (artifact-only)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase26h_counterfactual_consistency import (
    PHASE26G_JSON,
    PHASE26H_JSON,
    _build_causal_chain,
    _verify_scenario_consistency,
    run_phase26h_collection,
)


class TestPhase26HCausalChain(unittest.TestCase):
    def test_lot_baseline_chain(self) -> None:
        row = {
            "candidate": "t@354",
            "direction": "BUY",
            "baseline": "LOT",
            "A_no_lot": "ALLOWED",
            "B_no_meta": "LOT",
            "C_no_atr": "LOT",
            "D_no_lot_meta": "ALLOWED",
        }
        chain = _build_causal_chain(row)
        self.assertEqual(chain["blocker_type"], "DIRECT")
        self.assertIn("LOT(block)", chain["causal_chain"])

    def test_meta_baseline_exposes_lot(self) -> None:
        row = {
            "candidate": "t@357",
            "direction": "BUY",
            "baseline": "META",
            "B_no_meta": "LOT",
            "D_no_lot_meta": "ALLOWED",
            "C_no_atr": "META",
            "A_no_lot": "META",
        }
        chain = _build_causal_chain(row)
        self.assertEqual(chain["downstream_blocker"], "LOT")


class TestPhase26HConsistency(unittest.TestCase):
    def test_phase26g_artifact_internally_consistent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        g26 = root / PHASE26G_JSON
        if not g26.is_file():
            self.skipTest("phase26g artifact missing")
        payload = json.loads(g26.read_text(encoding="utf-8"))
        result = _verify_scenario_consistency(payload)
        self.assertTrue(result["passed"], msg=str(result["issues"]))

    def test_audit_generates_26h_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26G_JSON).is_file():
            self.skipTest("phase26g artifact missing")
        report = run_phase26h_collection(root)
        self.assertEqual(report["classification"]["primary"], "B — sequential blocker stack")
        self.assertEqual(report["production_changes"], "NONE")
        self.assertTrue((root / PHASE26H_JSON).is_file())
        self.assertEqual(len(report["causal_gate_matrix"]), 19)


if __name__ == "__main__":
    unittest.main()
