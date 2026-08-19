"""Phase 19D — final production certification tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase19d.capital import run_capital_simulation
from tradingbot.ml.phase19d.config import VERDICTS, reports_dir
from tradingbot.ml.phase19d.deployment import build_deployment_readiness
from tradingbot.ml.phase19d.montecarlo import run_montecarlo_certification
from tradingbot.ml.phase19d.scoring import compute_final_score
from tradingbot.ml.phase19d.stress_test import run_stress_test
from tradingbot.ml.phase19d.verdict import determine_verdict
from tradingbot.ml.phase19d.walkforward import run_walkforward_certification


def _trades(n: int = 60) -> list[dict]:
    out = []
    for i in range(n):
        win = i % 3 != 0
        out.append({
            "timestamp": f"2024-{(i % 12) + 1:02d}-01T10:00:00+00:00",
            "year": 2024,
            "month": (i % 12) + 1,
            "allowed": True,
            "pipeline_allowed": True,
            "regime": "TREND" if i % 2 else "RANGE",
            "adx": 20 + (i % 20),
            "rsi": 45 + (i % 10),
            "r_multiple": 2.0 if win else -1.0,
            "risk_percent": 0.005,
            "duration_bars": 2,
        })
    return out


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 3)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase19d")


class TestWalkforward(unittest.TestCase):
    def test_stable(self):
        r = run_walkforward_certification(_trades())
        self.assertIn("stable", r)
        self.assertGreater(r["n_folds"], 0)


class TestMonteCarlo(unittest.TestCase):
    def test_scenarios(self):
        r = run_montecarlo_certification(_trades(), seed=42)
        self.assertIn("random_trade_order", r.get("scenarios", {}))
        self.assertIn("execution_delay", r.get("scenarios", {}))


class TestStress(unittest.TestCase):
    def test_segments(self):
        r = run_stress_test(_trades())
        self.assertEqual(len(r["segments"]), 5)


class TestCapital(unittest.TestCase):
    def test_levels(self):
        r = run_capital_simulation(_trades())
        self.assertIn("200", r["levels"])
        self.assertIn("5000", r["levels"])


class TestScoring(unittest.TestCase):
    def test_score(self):
        cert = {
            "passed": True,
            "windows": {"1095d": {"performance": {
                "profit_factor": 1.5, "expectancy_r": 0.2, "win_rate": 0.45,
                "maximum_drawdown_r": -5,
            }}},
        }
        wf = {"stable": True, "passed": True}
        mc = {"passed": True, "max_failure_rate": 0.1}
        stress = {"passed": True}
        capital = {"levels": {"1000": {"risk_of_ruin": False, "total_return_pct": 5}}, "passed": True}
        live = {"passed": True}
        s = compute_final_score(
            certification=cert, walkforward=wf, montecarlo=mc,
            stress=stress, capital=capital, live_safety=live,
        )
        self.assertGreater(s["overall_score"], 0)


class TestVerdict(unittest.TestCase):
    def _deployment(self, all_pass: bool) -> dict:
        gates = {
            "backtest_certification": all_pass,
            "walkforward_stable": all_pass,
            "montecarlo_passed": all_pass,
            "stress_test_passed": all_pass,
            "capital_simulation_passed": all_pass,
            "live_safety_passed": all_pass,
            "final_audit_passed": all_pass,
        }
        return {"gates": gates, "all_gates_pass": all_pass}

    def test_full_production(self):
        cert = {"windows": {"1095d": {"performance": {
            "profit_factor": 1.35, "expectancy_r": 0.18, "maximum_drawdown_r": -10,
        }}}}
        v = determine_verdict(
            deployment=self._deployment(True),
            final_score={"overall_score": 75},
            certification=cert,
        )
        self.assertEqual(v, "APPROVED_FOR_FULL_PRODUCTION")

    def test_not_approved(self):
        v = determine_verdict(
            deployment=self._deployment(False),
            final_score={"overall_score": 30},
            certification={"windows": {"1095d": {"performance": {"profit_factor": 0.9}}}},
        )
        self.assertEqual(v, "NOT_APPROVED_FOR_LIVE")


class TestDeployment(unittest.TestCase):
    def test_gates(self):
        d = build_deployment_readiness(
            certification={"passed": True},
            walkforward={"passed": True},
            montecarlo={"passed": True},
            stress={"passed": True},
            capital={"passed": True},
            live_safety={"passed": True},
            audit={"passed": True},
        )
        self.assertTrue(d["all_gates_pass"])


if __name__ == "__main__":
    unittest.main()
