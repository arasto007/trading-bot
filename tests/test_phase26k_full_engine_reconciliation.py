"""Phase 26K — full-engine reconciliation tests (runtime-guarded)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase26i_full_tail_attribution import EXPECTED_CURSORS, EXPECTED_DIRECTIONS
from tradingbot.backtest.phase26k_full_engine_reconciliation import (
    EXPECTED_FINGERPRINT,
    EXPECTED_RISKGATE_REJECTS,
    PHASE26K_JSON,
    RUNTIME_BUDGET_SECONDS,
    classify_riskgate_rejection,
    compare_candidate_sets,
    compare_riskgate_counts,
    run_phase26k_collection,
)


class TestPhase26KExpectedSet(unittest.TestCase):
    def test_exact_19_candidate_set(self) -> None:
        self.assertEqual(len(EXPECTED_CURSORS), 19)
        expected = {
            354, 355, 356, 357, 358, 359,
            1175, 1176, 1177, 1178, 1179, 1180, 1186,
            1451, 1452, 1453, 1454, 1455, 1456,
        }
        self.assertEqual(EXPECTED_CURSORS, frozenset(expected))

    def test_directions_for_all_cursors(self) -> None:
        for cur in EXPECTED_CURSORS:
            self.assertIn(cur, EXPECTED_DIRECTIONS)
        self.assertEqual(sum(1 for d in EXPECTED_DIRECTIONS.values() if d == "BUY"), 13)
        self.assertEqual(sum(1 for d in EXPECTED_DIRECTIONS.values() if d == "SELL"), 6)


class TestPhase26KComparisonLogic(unittest.TestCase):
    def test_exact_match_detection(self) -> None:
        records = [
            {"cursor": c, "direction": EXPECTED_DIRECTIONS[c], "timestamp": f"t@{c}"}
            for c in sorted(EXPECTED_CURSORS)
        ]
        result = compare_candidate_sets(EXPECTED_CURSORS, records)
        self.assertEqual(result["classification"], "EXACT MATCH")
        self.assertTrue(result["passed"])

    def test_mismatch_detection_extra_cursor(self) -> None:
        extra = set(EXPECTED_CURSORS) | {9999}
        result = compare_candidate_sets(extra)
        self.assertEqual(result["classification"], "MISMATCH")
        self.assertFalse(result["passed"])
        self.assertIn(9999, result["extra"])

    def test_mismatch_detection_wrong_direction(self) -> None:
        records = [{"cursor": 354, "direction": "SELL"}]
        result = compare_candidate_sets({354}, records)
        self.assertFalse(result["passed"])

    def test_riskgate_bucket_classification(self) -> None:
        self.assertEqual(classify_riskgate_rejection("ATR percentile too high (97>96)"), "ATR")
        self.assertEqual(classify_riskgate_rejection("meta-labeler rejected (p=0.02)"), "META")
        self.assertEqual(classify_riskgate_rejection("lot too small"), "LOT")

    def test_riskgate_counts_exact_match(self) -> None:
        measured = {"ATR": 6, "META": 10, "LOT": 3, "OTHER": 0}
        result = compare_riskgate_counts(measured)
        self.assertTrue(result["passed"])
        self.assertEqual(result["classification"], "EXACT MATCH")

    def test_riskgate_counts_mismatch(self) -> None:
        result = compare_riskgate_counts({"ATR": 5, "META": 10, "LOT": 3, "OTHER": 0})
        self.assertFalse(result["passed"])


class TestPhase26KCollection(unittest.TestCase):
    def test_runtime_guard_defers_expensive_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / "data/backtest/XAUUSD_M5_183d.parquet").is_file():
            self.skipTest("dataset missing")
        report = run_phase26k_collection(root)
        self.assertIn("DEFERRED", report["status"])
        self.assertFalse(report["runtime"]["full_walk_executed"])
        probe = report["runtime"]["probe"]
        self.assertTrue(probe.get("probe_ran"))
        self.assertFalse(probe.get("within_budget"))
        self.assertGreater(probe.get("estimated_full_walk_seconds", 0), RUNTIME_BUDGET_SECONDS)

    def test_final_claim_remains_b_when_deferred(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / "data/backtest/XAUUSD_M5_183d.parquet").is_file():
            self.skipTest("dataset missing")
        report = run_phase26k_collection(root)
        self.assertEqual(
            report["final_zero_trade_claim"],
            "B — STRONGLY SUPPORTED BUT NOT FORMALLY PROVEN",
        )
        self.assertNotEqual(report["final_zero_trade_claim"], "A — VERIFIED FOR THE EXACT 2500-BAR FULL-ENGINE RUN")

    def test_no_production_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / "data/backtest/XAUUSD_M5_183d.parquet").is_file():
            self.skipTest("dataset missing")
        report = run_phase26k_collection(root)
        self.assertEqual(report["production_changes"], "NONE")
        self.assertFalse(report["safety"]["PRODUCTION_CODE_CHANGED"])
        self.assertFalse(report["safety"]["FULL_BACKTEST_RERUN"])
        self.assertTrue((root / PHASE26K_JSON).is_file())

    def test_dataset_fingerprint_and_window(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / "data/backtest/XAUUSD_M5_183d.parquet").is_file():
            self.skipTest("dataset missing")
        report = run_phase26k_collection(root)
        ds = report["dataset"]
        self.assertEqual(ds["bars"], 2500)
        self.assertEqual(ds["warmup"], 300)
        self.assertTrue(ds["fingerprint_matches_26b"])
        self.assertEqual(ds["configuration_fingerprint"], EXPECTED_FINGERPRINT)

    def test_execution_attempts_zero_when_not_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / "data/backtest/XAUUSD_M5_183d.parquet").is_file():
            self.skipTest("dataset missing")
        report = run_phase26k_collection(root)
        self.assertEqual(report["execution_attempts"], 0)
        self.assertTrue(report["execution_blocked_by_design"])

    def test_expected_riskgate_baseline_constants(self) -> None:
        self.assertEqual(EXPECTED_RISKGATE_REJECTS["ATR"], 6)
        self.assertEqual(EXPECTED_RISKGATE_REJECTS["META"], 10)
        self.assertEqual(EXPECTED_RISKGATE_REJECTS["LOT"], 3)


if __name__ == "__main__":
    unittest.main()
