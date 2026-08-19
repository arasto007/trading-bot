"""Phase 20C — real broker execution validation tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase20c.broker_data import load_broker_executions
from tradingbot.ml.phase20c.config import MIN_REAL_TRADES, VERDICTS, reports_dir
from tradingbot.ml.phase20c.execution_audit import audit_broker_execution
from tradingbot.ml.phase20c.latency import analyze_latency
from tradingbot.ml.phase20c.risk_validation import validate_risk
from tradingbot.ml.phase20c.scoring import compute_final_live_score
from tradingbot.ml.phase20c.slippage import analyze_slippage
from tradingbot.ml.phase20c.spread import analyze_spread
from tradingbot.ml.phase20c.stability import analyze_stability
from tradingbot.ml.phase20c.verdict import determine_verdict


def _empty_data() -> dict:
    return {
        "real_fills": [],
        "all_executions": [],
        "live_trades": [],
        "latency": [],
        "risk_events": [],
        "equity": [],
        "drawdown": [],
        "health": [],
        "session_summary": {},
        "final_report": {"mode": "init_only"},
        "real_fill_count": 0,
        "has_sufficient_trades": False,
        "min_required": MIN_REAL_TRADES,
        "files_present": {},
    }


def _filled_data(n: int = 6) -> dict:
    fills = []
    for i in range(n):
        fills.append({
            "timestamp": f"2024-01-0{(i % 9) + 1}T10:00:00+00:00",
            "symbol": "XAUUSD",
            "direction": "BUY" if i % 2 == 0 else "SELL",
            "ticket": 1000 + i,
            "success": True,
            "requested_price": 2000.0,
            "fill_price": 2000.1 + i * 0.01,
            "slippage": 0.1 + i * 0.01,
            "spread": 0.2,
            "execution_latency_ms": 20 + i,
            "volume": 0.01,
            "risk_percent": 0.02,
            "r_multiple": 2.0 if i % 3 else -1.0,
        })
    return {
        "real_fills": fills,
        "all_executions": fills + [{"success": False, "blocked": True, "message": "reject"}],
        "live_trades": fills,
        "latency": [{"latency_ms": 15.0}, {"latency_ms": 22.0}],
        "risk_events": [{"allowed": True}, {"allowed": False, "reason": "limit"}],
        "equity": [],
        "drawdown": [],
        "health": [{"safety": {"rollback_triggered": False, "kill_switch": {"active": False}}}],
        "session_summary": {},
        "final_report": {},
        "real_fill_count": n,
        "has_sufficient_trades": n >= MIN_REAL_TRADES,
        "min_required": MIN_REAL_TRADES,
        "files_present": {},
    }


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 2)

    def test_reports(self):
        self.assertEqual(reports_dir().name, "phase20c")


class TestWaiting(unittest.TestCase):
    def test_empty_waiting(self):
        data = _empty_data()
        audit = audit_broker_execution(data)
        self.assertEqual(audit["status"], "PENDING")
        slip = analyze_slippage(data, audit)
        self.assertEqual(slip["status"], "PENDING")
        risk = validate_risk(data)
        self.assertEqual(risk["status"], "PENDING")
        stab = analyze_stability(data)
        score = compute_final_live_score(
            data=data, audit=audit, slippage=slip, spread={"status": "PENDING"},
            latency={"status": "PENDING"}, sim_vs_live={"status": "PENDING"},
            risk=risk, stability=stab, broker_quality={"status": "PENDING"},
        )
        v = determine_verdict(data=data, risk=risk, stability=stab, score=score)
        self.assertEqual(v, "WAITING_FOR_REAL_TRADES")


class TestWithFills(unittest.TestCase):
    def test_audit_complete(self):
        data = _filled_data()
        audit = audit_broker_execution(data)
        self.assertEqual(audit["status"], "COMPLETE")
        self.assertGreater(audit["orders_analyzed"], 0)

    def test_slippage_spread(self):
        data = _filled_data()
        audit = audit_broker_execution(data)
        slip = analyze_slippage(data, audit)
        spr = analyze_spread(data, audit)
        self.assertEqual(slip["status"], "COMPLETE")
        self.assertEqual(spr["status"], "COMPLETE")

    def test_latency(self):
        data = _filled_data()
        audit = audit_broker_execution(data)
        lat = analyze_latency(data, audit)
        self.assertEqual(lat["status"], "COMPLETE")

    def test_risk_and_stability(self):
        data = _filled_data()
        risk = validate_risk(data)
        stab = analyze_stability(data)
        self.assertTrue(risk["passed"])
        self.assertTrue(stab["passed"])

    def test_live_validated(self):
        data = _filled_data(8)
        audit = audit_broker_execution(data)
        slip = analyze_slippage(data, audit)
        spr = analyze_spread(data, audit)
        lat = analyze_latency(data, audit)
        risk = validate_risk(data)
        stab = analyze_stability(data)
        score = compute_final_live_score(
            data=data, audit=audit, slippage=slip, spread=spr,
            latency=lat,
            sim_vs_live={"status": "COMPLETE", "delta": {"profit_factor": 0.1, "expectancy_r": 0.05}},
            risk=risk, stability=stab,
            broker_quality={"failure_rate": 0.1, "status": "COMPLETE"},
        )
        v = determine_verdict(data=data, risk=risk, stability=stab, score=score)
        self.assertEqual(v, "LIVE_VALIDATED")


class TestLoadEmpty(unittest.TestCase):
    def test_load_missing_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_broker_executions(tmp)
            self.assertEqual(data["real_fill_count"], 0)
            self.assertFalse(data["has_sufficient_trades"])


if __name__ == "__main__":
    unittest.main()
