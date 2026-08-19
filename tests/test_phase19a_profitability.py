"""Phase 19A — profitability audit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase19a.capital import analyze_capital
from tradingbot.ml.phase19a.config import CAPITAL_LEVELS, VERDICTS, reports_dir
from tradingbot.ml.phase19a.metrics import (
    compute_performance,
    consecutive_streaks,
    max_drawdown_r,
    pf_from_r,
    sharpe_r,
)
from tradingbot.ml.phase19a.regime_analysis import analyze_regimes
from tradingbot.ml.phase19a.robustness import run_robustness
from tradingbot.ml.phase19a.scoring import compute_final_score
from tradingbot.ml.phase19a.symbol_analysis import monthly_statistics, yearly_statistics
from tradingbot.ml.phase19a.trade_quality import analyze_trade_quality
from tradingbot.ml.phase19a.verdict import determine_verdict


def _trades(n: int = 50, *, win_rate: float = 0.55) -> list[dict]:
    out = []
    for i in range(n):
        win = (i % 100) / 100 < win_rate
        r = 2.0 if win else -1.0
        out.append({
            "allowed": True,
            "r_multiple": r,
            "regime": "TREND" if i % 3 else "RANGE",
            "year": 2024 + (i % 2),
            "month": (i % 12) + 1,
            "weekday": i % 5,
            "hour": i % 24,
            "mfe": 1.5,
            "mae": 0.5,
            "duration_bars": 10,
            "risk_percent": 0.005,
        })
    return out


class TestMetrics(unittest.TestCase):
    def test_pf(self):
        self.assertGreater(pf_from_r([2, 2, -1]), 1.0)

    def test_drawdown(self):
        self.assertLessEqual(max_drawdown_r([1, -2, 1]), 0)

    def test_streaks(self):
        s = consecutive_streaks([1, 1, -1, -1, -1, 1])
        self.assertEqual(s["max_consecutive_wins"], 2)
        self.assertEqual(s["max_consecutive_losses"], 3)

    def test_performance(self):
        p = compute_performance(_trades(20))
        self.assertGreater(p["trades"], 0)
        self.assertIn("profit_factor", p)

    def test_sharpe(self):
        self.assertIsInstance(sharpe_r([0.1, 0.2, -0.05]), float)


class TestRegime(unittest.TestCase):
    def test_split(self):
        r = analyze_regimes(_trades(30))
        self.assertIn("TREND", r["regimes"])
        self.assertIn("RANGE", r["regimes"])


class TestSymbol(unittest.TestCase):
    def test_monthly(self):
        m = monthly_statistics(_trades(40))
        self.assertTrue(len(m["months"]) > 0)

    def test_yearly(self):
        y = yearly_statistics(_trades(40))
        self.assertTrue(len(y["years"]) > 0)


class TestTradeQuality(unittest.TestCase):
    def test_quality(self):
        q = analyze_trade_quality(_trades(30))
        self.assertEqual(q["trades"], 30)


class TestRobustness(unittest.TestCase):
    def test_mc(self):
        r = run_robustness(_trades(60), seed=42)
        self.assertIn("scenarios", r)
        self.assertIn("random_trade_order", r["scenarios"])


class TestCapital(unittest.TestCase):
    def test_levels(self):
        c = analyze_capital(_trades(40))
        self.assertEqual(len(c["levels"]), len(CAPITAL_LEVELS))


class TestScoring(unittest.TestCase):
    def test_score(self):
        trades = _trades(50)
        perf = {
            "windows": {
                "1095d": {"performance": compute_performance(trades)},
                "365d": {"performance": compute_performance(trades)},
            }
        }
        rob = run_robustness(trades, seed=1)
        reg = analyze_regimes(trades)
        cap = analyze_capital(trades)
        s = compute_final_score(performance=perf, robustness=rob, regime=reg, capital=cap)
        self.assertIn("overall_score", s)


class TestVerdict(unittest.TestCase):
    def test_verdicts(self):
        trades = _trades(80, win_rate=0.6)
        perf = {
            "windows": {
                "365d": {"performance": compute_performance(trades)},
                "1095d": {"performance": compute_performance(trades)},
            }
        }
        rob = run_robustness(trades, seed=1)
        cap = analyze_capital(trades)
        score = compute_final_score(
            performance=perf, robustness=rob,
            regime=analyze_regimes(trades), capital=cap,
        )
        v = determine_verdict(
            performance_summary=perf, robustness=rob, capital=cap, final_score=score,
        )
        self.assertIn(v, VERDICTS)


class TestConfig(unittest.TestCase):
    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase19a")


# bulk

class TestBulkMetrics(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkRobust(unittest.TestCase):
    pass


class TestBulkCapital(unittest.TestCase):
    pass


def _bulk_metrics() -> None:
    for i in range(50):
        def test(self, idx=i):
            r = [2.0 if j % (3 + idx % 3) else -1.0 for j in range(30)]
            self.assertGreaterEqual(pf_from_r(r), 0.0)

        test.__name__ = f"test_bulk_pf_{i}"
        setattr(TestBulkMetrics, test.__name__, test)


def _bulk_verdict() -> None:
    for i in range(50):
        def test(self, idx=i):
            trades = _trades(40 + idx % 20, win_rate=0.5 + (idx % 10) * 0.02)
            perf = {"windows": {
                "365d": {"performance": compute_performance(trades)},
                "1095d": {"performance": compute_performance(trades)},
            }}
            rob = run_robustness(trades, seed=idx)
            cap = analyze_capital(trades)
            score = compute_final_score(
                performance=perf, robustness=rob,
                regime=analyze_regimes(trades), capital=cap,
            )
            self.assertIn(determine_verdict(
                performance_summary=perf, robustness=rob, capital=cap, final_score=score,
            ), VERDICTS)

        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _bulk_robust() -> None:
    for i in range(40):
        def test(self, idx=i):
            r = run_robustness(_trades(30 + idx), seed=idx)
            self.assertIn("baseline_pf", r)

        test.__name__ = f"test_bulk_robust_{i}"
        setattr(TestBulkRobust, test.__name__, test)


def _bulk_capital() -> None:
    for i in range(40):
        def test(self, idx=i):
            c = analyze_capital(_trades(25 + idx))
            self.assertIn("1000", c["levels"])

        test.__name__ = f"test_bulk_capital_{i}"
        setattr(TestBulkCapital, test.__name__, test)


_bulk_metrics()
_bulk_verdict()
_bulk_robust()
_bulk_capital()


if __name__ == "__main__":
    unittest.main()
