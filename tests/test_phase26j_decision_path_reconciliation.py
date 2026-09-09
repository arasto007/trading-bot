"""Phase 26J — decision-path reconciliation tests (lightweight)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase26i_full_tail_attribution import (
    EXPECTED_CURSORS,
    EXPECTED_DIRECTIONS,
    _verify_26c_funnel_internal,
    _verify_candidate_set,
)
from tradingbot.backtest.phase26j_decision_path_reconciliation import (
    PHASE26C_JSON,
    PHASE26G_JSON,
    PHASE26H_JSON,
    PHASE26J_JSON,
    run_phase26j_collection,
)


class TestPhase26JCandidateSet(unittest.TestCase):
    def test_exact_19_candidate_set_matches(self) -> None:
        root = Path(__file__).resolve().parents[1]
        d26 = json.loads((root / "logs/phase26d_kernel_signal_trace.json").read_text(encoding="utf-8"))
        g26 = json.loads((root / PHASE26G_JSON).read_text(encoding="utf-8"))
        result = _verify_candidate_set(d26, g26)
        self.assertTrue(result["passed"], msg=str(result["issues"]))
        self.assertEqual(result["phase26d_count"], 19)
        self.assertEqual(len(EXPECTED_CURSORS), 19)

    def test_candidate_directions_match(self) -> None:
        root = Path(__file__).resolve().parents[1]
        d26 = json.loads((root / "logs/phase26d_kernel_signal_trace.json").read_text(encoding="utf-8"))
        for row in d26["propagation_counts"]["per_candidate"]:
            cur = int(row["cursor"])
            self.assertIn(cur, EXPECTED_CURSORS)
            self.assertEqual(row["direction"], EXPECTED_DIRECTIONS[cur])


class TestPhase26JFunnelAndRiskGate(unittest.TestCase):
    def test_phase26c_funnel_consistent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        c26 = json.loads((root / PHASE26C_JSON).read_text(encoding="utf-8"))
        self.assertTrue(_verify_26c_funnel_internal(c26)["passed"])

    def test_19_to_19_riskgate_reach(self) -> None:
        root = Path(__file__).resolve().parents[1]
        d26 = json.loads((root / "logs/phase26d_kernel_signal_trace.json").read_text(encoding="utf-8"))
        prop = d26["propagation_counts"]
        self.assertEqual(prop["candidates"], 19)
        self.assertEqual(prop["risk_stage_reached"], 19)
        self.assertEqual(prop["signal_filter_pass"], 19)

    def test_baseline_lot_meta_atr_allowed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        g26 = json.loads((root / PHASE26G_JSON).read_text(encoding="utf-8"))
        baseline = g26["baseline"]
        self.assertEqual(baseline["LOT"], 3)
        self.assertEqual(baseline["META"], 10)
        self.assertEqual(baseline["ATR"], 6)
        self.assertEqual(baseline["ALLOWED"], 0)


class TestPhase26JReconciliation(unittest.TestCase):
    def test_zero_allowed_reconciles_zero_trades(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26C_JSON).is_file():
            self.skipTest("artifacts missing")
        report = run_phase26j_collection(root)
        exec_rec = report["execution_reconciliation"]
        self.assertTrue(exec_rec["reconciles"])
        self.assertEqual(exec_rec["phase26b_total_trades"], 0)
        self.assertEqual(exec_rec["riskgate_allowed"], 0)

    def test_forming_bar_not_counted_as_production(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26C_JSON).is_file():
            self.skipTest("artifacts missing")
        report = run_phase26j_collection(root)
        fb = report["forming_bar_effect"]
        self.assertFalse(fb["forming_only_transients_counted_as_production"])
        self.assertFalse(fb["reran_forming_comparison"])
        counts = fb["phase26c_counts"]
        self.assertEqual(counts["forming_bar_sim_pass"], counts["price_action_strategy_signals"])

    def test_no_production_changes_no_full_engine(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26C_JSON).is_file():
            self.skipTest("artifacts missing")
        report = run_phase26j_collection(root)
        self.assertEqual(report["production_changes"], "NONE")
        self.assertFalse(report["reran_full_backtest"])
        self.assertFalse(report["full_engine_simultaneous_bar_walk"])
        self.assertFalse(report["safety"]["FULL_BACKTEST_RERUN"])
        self.assertTrue((root / PHASE26J_JSON).is_file())

    def test_final_claim_is_conservative(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26C_JSON).is_file():
            self.skipTest("artifacts missing")
        report = run_phase26j_collection(root)
        self.assertEqual(report["final_zero_trade_claim"], "B — STRONGLY SUPPORTED BUT NOT FORMALLY PROVEN")
        self.assertNotEqual(report["final_zero_trade_claim"], "A — PROVEN END-TO-END")

    def test_signal_scan_no_riskgate_or_execution(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / PHASE26C_JSON).is_file():
            self.skipTest("artifacts missing")
        report = run_phase26j_collection(root)
        scan = report["additional_signals"]["signal_scan"]
        if scan.get("ran"):
            self.assertFalse(scan["uses_riskgate"])
            self.assertFalse(scan["uses_broker_simulation"])
            self.assertFalse(scan["uses_execution"])
            self.assertTrue(scan["cursor_set_matches_expected"])


if __name__ == "__main__":
    unittest.main()
