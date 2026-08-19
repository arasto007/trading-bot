"""Phase 27O — OOS hybrid exit deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27o"

DELIVERABLES = [
    "train_results.json",
    "validation_results.json",
    "generalization_gap.json",
    "out_of_sample_metrics.json",
    "montecarlo_validation.json",
    "ranking.json",
    "phase27o_final_report.json",
]

VERDICTS = {"HYBRID_READY_FOR_IMPLEMENTATION", "HYBRID_NOT_GENERALIZING", "HYBRID_INCONCLUSIVE"}
COMPARE = {
    "current_tp_sl",
    "time_exit",
    "partial_close_50",
    "structure_exit",
    "hybrid_a",
    "hybrid_d",
    "hybrid_b",
}


class TestPhase27ODeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase27o_final_report.json").is_file():
            raise unittest.SkipTest("Phase 27O deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase27o_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_train_validation_splits(self) -> None:
        train = json.loads((PHASE_DIR / "train_results.json").read_text(encoding="utf-8"))
        val = json.loads((PHASE_DIR / "validation_results.json").read_text(encoding="utf-8"))
        self.assertGreater(train.get("total_trades", 0), 0)
        self.assertGreater(val.get("total_trades", 0), 0)
        self.assertLess(val["total_trades"], train["total_trades"])

    def test_generalization_hybrid_b(self) -> None:
        gen = json.loads((PHASE_DIR / "generalization_gap.json").read_text(encoding="utf-8"))
        self.assertIn("hybrid_b", gen.get("by_strategy") or {})
        self.assertIn("hybrid_b_summary", gen)

    def test_oos_metrics_windows(self) -> None:
        oos = json.loads((PHASE_DIR / "out_of_sample_metrics.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(oos.get("windows") or {}), 3)

    def test_ranking_includes_all_strategies(self) -> None:
        rank = json.loads((PHASE_DIR / "ranking.json").read_text(encoding="utf-8"))
        ranked = {r["strategy"] for r in (rank.get("ranked") or [])}
        self.assertTrue(COMPARE.issubset(ranked))

    def test_montecarlo_1000_sims(self) -> None:
        mc = json.loads((PHASE_DIR / "montecarlo_validation.json").read_text(encoding="utf-8"))
        seq = (mc.get("strategies") or {}).get("hybrid_b", {}).get("sequence_shuffle", {})
        self.assertEqual(seq.get("simulations"), 1000)


if __name__ == "__main__":
    unittest.main()
