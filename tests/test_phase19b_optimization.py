"""Phase 19B — research profitability optimization tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase19b.config import TARGET_PF, VERDICTS, reports_dir
from tradingbot.ml.research.phase19b.exit_study import study_exits
from tradingbot.ml.research.phase19b.filters import discover_filters
from tradingbot.ml.research.phase19b.loss_analysis import analyze_losses
from tradingbot.ml.research.phase19b.montecarlo import stress_candidate
from tradingbot.ml.research.phase19b.position_sizing import study_position_sizing
from tradingbot.ml.research.phase19b.recommendations import build_recommendations
from tradingbot.ml.research.phase19b.verdict import determine_verdict
from tradingbot.ml.research.phase19b.walkforward import validate_candidate
from tradingbot.ml.research.phase19b.winner_analysis import analyze_winners


def _trades(n: int = 80) -> list[dict]:
    out = []
    for i in range(n):
        win = i % 3 != 0
        r = 2.0 if win else -1.0
        out.append({
            "timestamp": f"2024-{(i % 12) + 1:02d}-01T{(i % 24):02d}:00:00+00:00",
            "year": 2024 + (i // 40),
            "month": (i % 12) + 1,
            "weekday": i % 5,
            "hour": i % 24,
            "session": "LONDON" if 8 <= (i % 24) < 13 else "NY",
            "regime": "RANGE" if i % 2 == 0 else "TREND",
            "allowed": True,
            "confidence": 0.4 + (i % 5) * 0.05,
            "quality_score": 0.5 + (i % 4) * 0.05,
            "risk_percent": 0.005,
            "r_multiple": r,
            "mfe": 1.5 if win else 0.3,
            "mae": 0.4 if win else 1.2,
            "duration_bars": 2 if win else 1,
            "sl_distance": 1.0,
            "tp_distance": 2.0,
            "is_win": win,
            "is_loss": not win,
            "adx": 20 + (i % 20),
            "atr": 1.0 + (i % 10) * 0.1,
            "rsi": 40 + (i % 30),
            "spread": 0.1 + (i % 5) * 0.02,
            "trend_age": float(i % 30),
        })
    return out


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 2)

    def test_reports(self):
        self.assertEqual(reports_dir().name, "phase19b")

    def test_target_pf(self):
        self.assertEqual(TARGET_PF, 1.30)


class TestLossWinner(unittest.TestCase):
    def test_loss(self):
        r = analyze_losses(_trades())
        self.assertGreater(r["losing_trades"], 0)
        self.assertIn("recurring_patterns", r)

    def test_winners(self):
        r = analyze_winners(_trades())
        self.assertGreater(r["winning_trades"], 0)
        self.assertTrue(r["ranked_predictors"])


class TestFilters(unittest.TestCase):
    def test_discover(self):
        r = discover_filters(_trades())
        self.assertIn("single_filters", r)
        self.assertTrue(len(r["single_filters"]) > 0)


class TestExitSizing(unittest.TestCase):
    def test_exit(self):
        r = study_exits(_trades())
        self.assertTrue(r["variants"])

    def test_sizing(self):
        r = study_position_sizing(_trades())
        self.assertTrue(r["variants"])


class TestWalkMc(unittest.TestCase):
    def test_wf(self):
        r = validate_candidate("hour_8_20", _trades(100))
        self.assertIn("stable", r)

    def test_mc(self):
        r = stress_candidate("hour_8_20", _trades(100), seed=1)
        self.assertIn("passed", r)


class TestVerdict(unittest.TestCase):
    def test_no_safe(self):
        rec = {"safe_improvements": []}
        self.assertEqual(determine_verdict(rec), "NO_SAFE_IMPROVEMENT_FOUND")

    def test_safe(self):
        rec = {"safe_improvements": [{
            "expected_impact": {"profit_factor": 0.1, "expectancy": 0.05, "max_drawdown": -1},
        }]}
        self.assertEqual(determine_verdict(rec), "SAFE_IMPROVEMENTS_AVAILABLE")

    def test_recommendations_shape(self):
        trades = _trades()
        filters = discover_filters(trades)
        exits = study_exits(trades)
        sizing = study_position_sizing(trades)
        rec = build_recommendations(
            trades,
            filter_report=filters,
            exit_report=exits,
            sizing_report=sizing,
            walkforward={"survivors": []},
            montecarlo={"passed": []},
        )
        self.assertIn("baseline", rec)
        self.assertIn("safe_improvements", rec)


# bulk

class TestBulkLoss(unittest.TestCase):
    pass


class TestBulkFilter(unittest.TestCase):
    pass


class TestBulkExit(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


def _bulk() -> None:
    for i in range(40):
        def t1(self, idx=i):
            r = analyze_losses(_trades(40 + idx))
            self.assertGreaterEqual(r["total_trades"], 40)

        t1.__name__ = f"test_bulk_loss_{i}"
        setattr(TestBulkLoss, t1.__name__, t1)

    for i in range(40):
        def t2(self, idx=i):
            r = discover_filters(_trades(50 + idx % 10))
            self.assertIn("baseline", r)

        t2.__name__ = f"test_bulk_filter_{i}"
        setattr(TestBulkFilter, t2.__name__, t2)

    for i in range(40):
        def t3(self, idx=i):
            r = study_exits(_trades(30 + idx % 5))
            self.assertTrue(any(v["name"] for v in r["variants"]))

        t3.__name__ = f"test_bulk_exit_{i}"
        setattr(TestBulkExit, t3.__name__, t3)

    for i in range(40):
        def t4(self, idx=i):
            impact = {"profit_factor": 0.1 if idx % 2 else -0.1, "expectancy": 0.01, "max_drawdown": 0}
            rec = {"safe_improvements": [{"expected_impact": impact}] if idx % 2 else []}
            self.assertIn(determine_verdict(rec), VERDICTS)

        t4.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, t4.__name__, t4)


_bulk()


if __name__ == "__main__":
    unittest.main()
