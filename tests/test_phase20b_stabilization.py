"""Phase 20B — live stabilization tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase20b.capital import simulate_capital_progression
from tradingbot.ml.phase20b.config import VERDICTS, reports_dir
from tradingbot.ml.phase20b.drawdown import analyze_drawdown
from tradingbot.ml.phase20b.execution import analyze_execution
from tradingbot.ml.phase20b.filters import analyze_filter_effectiveness
from tradingbot.ml.phase20b.health import compute_system_health
from tradingbot.ml.phase20b.performance import analyze_live_performance
from tradingbot.ml.phase20b.trade_quality import score_trades
from tradingbot.ml.phase20b.verdict import determine_verdict


def _obs(n: int = 40) -> dict:
    trades = []
    all_recs = []
    for i in range(n):
        win = i % 3 != 0
        r = 2.0 if win else -1.0
        row = {
            "timestamp": f"2024-{(i % 12) + 1:02d}-01T10:00:00+00:00",
            "allowed": True,
            "pipeline_allowed": True,
            "filter_passed": True,
            "regime": "TREND" if i % 2 else "RANGE",
            "r_multiple": r,
            "mfe": 2.0 if win else 0.3,
            "mae": -0.3 if win else -1.0,
            "duration_bars": 2,
            "confidence": 0.55,
            "risk_percent": 0.02,
            "rsi": 45 + (i % 10),
            "adx": 20 + (i % 15),
        }
        trades.append(row)
        all_recs.append(row)
        # some blocked by filter
        if i % 5 == 0:
            blocked = dict(row)
            blocked["rsi"] = 20
            blocked["allowed"] = False
            blocked["pipeline_allowed"] = True
            blocked["r_multiple"] = -1.0
            all_recs.append(blocked)
    baseline = [dict(t) for t in all_recs if t.get("pipeline_allowed")]
    return {
        "data_source": "live_path_observation",
        "broker_live_samples": 0,
        "trades": trades,
        "all_path_records": all_recs,
        "baseline_trades": baseline,
        "executions": [],
        "latency": [{"latency_ms": 12.0}, {"latency_ms": 18.0}],
        "equity": [],
        "drawdown": [],
        "risk_events": [],
        "health": [],
        "path_observation_available": True,
    }


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 2)

    def test_reports(self):
        self.assertEqual(reports_dir().name, "phase20b")


class TestModules(unittest.TestCase):
    def test_performance(self):
        p = analyze_live_performance(_obs())
        self.assertGreater(p["trades_observed"], 0)
        self.assertIn("TREND", p["by_regime"])

    def test_drawdown(self):
        d = analyze_drawdown(_obs())
        self.assertIn("maximum_drawdown_r", d)

    def test_quality(self):
        q = score_trades(_obs())
        self.assertGreater(q["mean_overall_quality"], 0)

    def test_execution(self):
        e = analyze_execution(_obs())
        self.assertTrue(e["passed"])

    def test_filters(self):
        f = analyze_filter_effectiveness(_obs())
        self.assertIn("rsi_filter", f)
        self.assertIn("classification", f["rsi_filter"])

    def test_capital(self):
        c = simulate_capital_progression(_obs())
        self.assertIn("2pct", c["levels"])

    def test_health_and_verdict(self):
        obs = _obs()
        perf = analyze_live_performance(obs)
        dd = analyze_drawdown(obs)
        ex = analyze_execution(obs)
        filt = analyze_filter_effectiveness(obs)
        cap = simulate_capital_progression(obs)
        tq = score_trades(obs)
        health = compute_system_health(
            performance=perf, drawdown=dd, execution=ex,
            filters=filt, capital=cap, trade_quality=tq,
        )
        self.assertGreater(health["overall_score"], 0)
        v = determine_verdict(
            observation=obs, performance=perf, drawdown=dd,
            execution=ex, health=health, capital=cap,
        )
        self.assertIn(v, VERDICTS)


class TestUnstable(unittest.TestCase):
    def test_empty_trades_unstable(self):
        obs = {
            "data_source": "broker_live",
            "trades": [],
            "path_observation_available": False,
            "broker_live_samples": 0,
        }
        perf = analyze_live_performance(obs)
        dd = analyze_drawdown(obs)
        ex = analyze_execution(obs)
        health = {"overall_score": 10}
        cap = {"passed": False}
        v = determine_verdict(
            observation=obs, performance=perf, drawdown=dd,
            execution=ex, health=health, capital=cap,
        )
        self.assertEqual(v, "LIVE_SYSTEM_UNSTABLE")


if __name__ == "__main__":
    unittest.main()
