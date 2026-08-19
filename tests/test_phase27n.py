"""Phase 27N — hybrid exit deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27n"

DELIVERABLES = [
    "hybrid_a.json",
    "hybrid_b.json",
    "hybrid_c.json",
    "hybrid_d.json",
    "hybrid_e.json",
    "comparison_matrix.json",
    "equity_comparison.json",
    "risk_comparison.json",
    "stability_report.json",
    "montecarlo_report.json",
    "global_ranking.json",
    "phase27n_final_report.json",
]

VERDICTS = {"HYBRID_EXIT_OUTPERFORMS_ALL", "HYBRID_EXIT_NOT_BETTER", "HYBRID_EXIT_INCONCLUSIVE"}
HYBRIDS = {"hybrid_a", "hybrid_b", "hybrid_c", "hybrid_d", "hybrid_e"}


class TestPhase27NDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase27n_final_report.json").is_file():
            raise unittest.SkipTest("Phase 27N deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase27n_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_hybrid_reports_have_windows(self) -> None:
        for h in HYBRIDS:
            data = json.loads((PHASE_DIR / f"{h}.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(data.get("windows") or {}), 3)

    def test_global_ranking_includes_hybrids(self) -> None:
        gr = json.loads((PHASE_DIR / "global_ranking.json").read_text(encoding="utf-8"))
        ranked = {r["strategy"] for r in (gr.get("ranked") or [])}
        self.assertTrue(HYBRIDS.issubset(ranked))
        self.assertTrue(gr.get("best_hybrid"))

    def test_equity_comparison(self) -> None:
        eq = json.loads((PHASE_DIR / "equity_comparison.json").read_text(encoding="utf-8"))
        self.assertIn("smoothest_equity_curve", eq)
        self.assertIn("current_tp_sl", eq.get("equity_curves") or {})

    def test_montecarlo_1000_sims(self) -> None:
        mc = json.loads((PHASE_DIR / "montecarlo_report.json").read_text(encoding="utf-8"))
        seq = (mc.get("strategies") or {}).get("hybrid_a", {}).get("sequence_shuffle", {})
        self.assertEqual(seq.get("simulations"), 1000)

    def test_stability_report(self) -> None:
        stab = json.loads((PHASE_DIR / "stability_report.json").read_text(encoding="utf-8"))
        self.assertIn("hybrid_a", (stab.get("by_strategy") or {}))


if __name__ == "__main__":
    unittest.main()
