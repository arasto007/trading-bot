"""Phase 27H — robustness stress test deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27h"
PHASE27G_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27g"

DELIVERABLES = [
    "spread_stress.json",
    "slippage_stress.json",
    "execution_delay.json",
    "missed_trade_montecarlo.json",
    "sequence_montecarlo.json",
    "cost_analysis.json",
    "rr_distribution.json",
    "confidence_robustness.json",
    "regime_robustness.json",
    "failure_simulation.json",
    "robustness_score.json",
    "final_report.json",
]

VERDICTS = {"ROBUST_FOR_PAPER", "NOT_ROBUST_FOR_PAPER"}
EXPECTED_TRADES = 575


class TestPhase27HDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "final_report.json").is_file():
            raise unittest.SkipTest("Phase 27H deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_trade_count_matches_baseline(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("completed_trades"), EXPECTED_TRADES)

    def test_spread_stress_scenarios(self) -> None:
        spread = json.loads((PHASE_DIR / "spread_stress.json").read_text(encoding="utf-8"))
        for key in ("+25%", "+50%", "+100%"):
            self.assertIn(key, spread.get("scenarios", {}))

    def test_slippage_levels(self) -> None:
        slip = json.loads((PHASE_DIR / "slippage_stress.json").read_text(encoding="utf-8"))
        scenarios = slip.get("scenarios") or {}
        self.assertIn("0.25_ATR", scenarios)
        self.assertIn("1.00_ATR", scenarios)

    def test_montecarlo_simulations(self) -> None:
        missed = json.loads((PHASE_DIR / "missed_trade_montecarlo.json").read_text(encoding="utf-8"))
        seq = json.loads((PHASE_DIR / "sequence_montecarlo.json").read_text(encoding="utf-8"))
        self.assertEqual(missed.get("simulations_per_level"), 100)
        self.assertEqual(seq.get("simulations"), 1000)

    def test_robustness_scores_range(self) -> None:
        scores = json.loads((PHASE_DIR / "robustness_score.json").read_text(encoding="utf-8"))
        for key in (
            "execution_robustness",
            "market_robustness",
            "risk_robustness",
            "monte_carlo_stability",
            "overall_robustness",
        ):
            val = scores.get(key, -1)
            self.assertGreaterEqual(val, 0)
            self.assertLessEqual(val, 100)

    def test_baseline_aligned_with_phase27g(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        baseline = report.get("baseline_metrics") or {}
        if (PHASE27G_DIR / "profitability_report.json").is_file():
            g27 = json.loads((PHASE27G_DIR / "profitability_report.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(baseline.get("net_profit"), g27.get("net_profit"), places=1)
            self.assertAlmostEqual(float(baseline.get("profit_factor")), float(g27.get("profit_factor")), places=2)


if __name__ == "__main__":
    unittest.main()
