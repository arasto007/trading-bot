"""Phase 26I — full-tail zero-trade attribution audit tests (artifact-only)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase26i_full_tail_attribution import (
    EXPECTED_CURSORS,
    PHASE26C_JSON,
    PHASE26G_JSON,
    PHASE26H_JSON,
    PHASE26I_JSON,
    _verify_26c_funnel_internal,
    _verify_26g_26h_baseline,
    _verify_candidate_set,
    run_phase26i_collection,
)


class TestPhase26ICandidateSet(unittest.TestCase):
    def test_expected_cursor_count_is_19(self) -> None:
        self.assertEqual(len(EXPECTED_CURSORS), 19)

    def test_candidate_ids_match_across_26d_26g(self) -> None:
        root = Path(__file__).resolve().parents[1]
        d26_path = root / "logs/phase26d_kernel_signal_trace.json"
        g26_path = root / PHASE26G_JSON
        if not d26_path.is_file() or not g26_path.is_file():
            self.skipTest("phase26d/26g artifacts missing")
        d26 = json.loads(d26_path.read_text(encoding="utf-8"))
        g26 = json.loads(g26_path.read_text(encoding="utf-8"))
        result = _verify_candidate_set(d26, g26)
        self.assertTrue(result["passed"], msg=str(result["issues"]))
        self.assertEqual(result["phase26d_count"], 19)
        self.assertEqual(result["phase26g_count"], 19)
        self.assertTrue(result["sets_identical"])


class TestPhase26CFunnelConsistency(unittest.TestCase):
    def test_phase26c_funnel_internally_consistent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        c26_path = root / PHASE26C_JSON
        if not c26_path.is_file():
            self.skipTest("phase26c artifact missing")
        c26 = json.loads(c26_path.read_text(encoding="utf-8"))
        result = _verify_26c_funnel_internal(c26)
        self.assertTrue(result["passed"], msg=str(result["issues"]))


class TestPhase26G26HBaseline(unittest.TestCase):
    def test_baseline_and_matrix_match(self) -> None:
        root = Path(__file__).resolve().parents[1]
        g_path = root / PHASE26G_JSON
        h_path = root / PHASE26H_JSON
        if not g_path.is_file() or not h_path.is_file():
            self.skipTest("phase26g/26h artifacts missing")
        g26 = json.loads(g_path.read_text(encoding="utf-8"))
        h26 = json.loads(h_path.read_text(encoding="utf-8"))
        result = _verify_26g_26h_baseline(g26, h26)
        self.assertTrue(result["passed"], msg=str(result["issues"]))
        self.assertEqual(result["expected_baseline"]["ALLOWED"], 0)


class TestPhase26ISequentialInterpretation(unittest.TestCase):
    def test_sequential_not_conjunction(self) -> None:
        root = Path(__file__).resolve().parents[1]
        h_path = root / PHASE26H_JSON
        if not h_path.is_file():
            self.skipTest("phase26h artifact missing")
        h26 = json.loads(h_path.read_text(encoding="utf-8"))
        classification = h26["classification"]
        self.assertEqual(classification["primary"], "B — sequential blocker stack")
        self.assertIn("Conjunction", classification["rejects_26g_wording"])


class TestPhase26IZeroTradeClaim(unittest.TestCase):
    def test_audit_does_not_upgrade_zero_trade_to_fully_proven(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26C_JSON).is_file():
            self.skipTest("phase26c artifact missing")
        report = run_phase26i_collection(root)
        answer = report["answers"]["is_full_tail_zero_trade_proven"]
        self.assertIn("PARTIALLY", answer)
        self.assertIn("NOT upgraded", " ".join(report["what_this_proves"]))

    def test_zero_allowed_among_19_attributed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26G_JSON).is_file():
            self.skipTest("phase26g artifact missing")
        report = run_phase26i_collection(root)
        attr = report["nineteen_candidate_riskgate_attribution"]
        self.assertEqual(attr["allowed"], 0)
        self.assertEqual(attr["baseline"]["LOT"], 3)
        self.assertEqual(attr["baseline"]["META"], 10)
        self.assertEqual(attr["baseline"]["ATR"], 6)


class TestPhase26IProductionSafety(unittest.TestCase):
    def test_no_production_configuration_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26C_JSON).is_file():
            self.skipTest("phase26c artifact missing")
        report = run_phase26i_collection(root)
        self.assertEqual(report["production_changes"], "NONE")
        self.assertFalse(report["reran_backtest"])
        self.assertFalse(report["safety"]["MT5_STARTED"])
        self.assertFalse(report["safety"]["STRATEGY_CHANGED"])
        self.assertFalse(report["safety"]["RISKGATE_CHANGED"])
        self.assertTrue((root / PHASE26I_JSON).is_file())


if __name__ == "__main__":
    unittest.main()
