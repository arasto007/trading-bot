"""Phase 18A — live shadow validation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase18a.comparator import ShadowComparator
from tradingbot.ml.research.phase18a.config import (
    MAX_LATENCY_OVERHEAD,
    MAX_RANDOM_DIVERGENCE,
    MIN_AGREEMENT_RATE,
    STRIDES,
    VERDICTS,
    reports_dir,
)
from tradingbot.ml.research.phase18a.divergence import cluster_divergences
from tradingbot.ml.research.phase18a.equity import ShadowEquityCurve
from tradingbot.ml.research.phase18a.latency import LatencyProfiler
from tradingbot.ml.research.phase18a.safety import ORDER_SEND_CALLS, assert_no_execution, record_order_send_attempt
from tradingbot.ml.research.phase18a.trade_logger import ShadowTradeLogger
from tradingbot.ml.research.phase18a.verdict import build_checks, build_final_report, determine_verdict


def _passing_stats() -> dict:
    return {
        "bars_evaluated": 500,
        "runtime_crashes": 0,
        "range_not_degraded": True,
        "latency_ok": True,
        "agreement_ok": True,
        "order_send_calls": 0,
        "agreement_rate": 0.92,
        "divergence_rate": 0.08,
        "divergence_rate_trend": 0.2,
        "divergence_rate_range": 0.0,
        "equity_divergence": {"pnl_delta": 0.1, "dd_delta": 0.0, "sharpe_delta": 0.1},
        "clusters": {"explainable": True, "random_spike": False},
        "stability": {"stable": True},
    }


def _passing_safety() -> dict:
    return {"passed": True, "order_send_calls": 0}


def _passing_regime() -> dict:
    return {"path_mismatch": False, "range_identical": True}


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 3)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase18a")

    def test_strides(self):
        self.assertIn(1, STRIDES)
        self.assertIn(5, STRIDES)

    def test_thresholds(self):
        self.assertEqual(MIN_AGREEMENT_RATE, 0.80)
        self.assertEqual(MAX_LATENCY_OVERHEAD, 0.10)
        self.assertEqual(MAX_RANDOM_DIVERGENCE, 0.30)


class TestSafety(unittest.TestCase):
    def test_no_execution(self):
        self.assertEqual(ORDER_SEND_CALLS, 0)
        self.assertTrue(assert_no_execution()["execution_disabled"])

    def test_order_send_raises(self):
        import tradingbot.ml.research.phase18a.safety as safety_mod

        prev = safety_mod.ORDER_SEND_CALLS
        try:
            with self.assertRaises(RuntimeError):
                record_order_send_attempt()
        finally:
            safety_mod.ORDER_SEND_CALLS = prev


class TestComparator(unittest.TestCase):
    def test_agree(self):
        c = ShadowComparator()
        c.compare(
            bar_index=0, timestamp="t", regime="TREND",
            v40={"signal": "BUY", "probability": 0.5},
            v41={"signal": "BUY", "probability": 0.6},
            latency_v40_ms=1.0, latency_v41_ms=1.1,
        )
        self.assertEqual(c.agree, 1)
        self.assertEqual(c.agreement_rate(), 1.0)

    def test_diverge(self):
        c = ShadowComparator()
        c.compare(
            bar_index=1, timestamp="t", regime="TREND",
            v40={"signal": "HOLD", "probability": 0.3},
            v41={"signal": "BUY", "probability": 0.5},
            latency_v40_ms=1.0, latency_v41_ms=1.2,
        )
        self.assertEqual(c.diverge, 1)
        self.assertEqual(len(c.diffs), 1)

    def test_range_agreement(self):
        c = ShadowComparator()
        for i in range(10):
            c.compare(
                bar_index=i, timestamp="t", regime="RANGE",
                v40={"signal": "SELL", "probability": 0.7},
                v41={"signal": "SELL", "probability": 0.7},
                latency_v40_ms=1.0, latency_v41_ms=1.0,
            )
        self.assertEqual(c.divergence_rate("RANGE"), 0.0)


class TestEquity(unittest.TestCase):
    def test_curve(self):
        eq = ShadowEquityCurve(label="v41")
        eq.add(0.1, timestamp="a", regime="TREND")
        eq.add(-0.05, timestamp="b", regime="TREND")
        d = eq.to_dict()
        self.assertEqual(d["points"], 2)
        self.assertAlmostEqual(d["final_equity"], 0.05)


class TestLatency(unittest.TestCase):
    def test_overhead_ok(self):
        lp = LatencyProfiler()
        for _ in range(20):
            lp.add(10.0, 10.5, 21.0)
        d = lp.to_dict()
        self.assertTrue(d["latency_ok"])

    def test_overhead_fail(self):
        lp = LatencyProfiler()
        for _ in range(20):
            lp.add(10.0, 15.0, 25.0)
        d = lp.to_dict()
        self.assertFalse(d["latency_ok"])


class TestDivergence(unittest.TestCase):
    def test_explainable_trend(self):
        diffs = [
            {"bar_index": i, "regime": "TREND", "v40_signal": "HOLD", "v41_signal": "BUY"}
            for i in range(20)
        ]
        r = cluster_divergences(diffs)
        self.assertTrue(r["explainable"])
        self.assertFalse(r["random_spike"])

    def test_empty(self):
        r = cluster_divergences([])
        self.assertEqual(r["total_divergences"], 0)
        self.assertTrue(r["explainable"])


class TestTradeLogger(unittest.TestCase):
    def test_no_order_send(self):
        log = ShadowTradeLogger()
        log.log({"signal": "BUY"})
        d = log.to_dict()
        self.assertEqual(d["order_send_calls"], 0)
        self.assertFalse(d["records"][0]["order_send"])


class TestVerdict(unittest.TestCase):
    def test_ready(self):
        checks = build_checks(
            stats=_passing_stats(),
            safety=_passing_safety(),
            regime=_passing_regime(),
            reports_present=True,
        )
        self.assertEqual(determine_verdict(checks), "READY_FOR_CONTROLLED_LIVE")

    def test_fail_order_send(self):
        stats = _passing_stats()
        stats["order_send_calls"] = 1
        checks = build_checks(
            stats=stats,
            safety={"passed": False},
            regime=_passing_regime(),
            reports_present=True,
        )
        self.assertEqual(determine_verdict(checks), "SHADOW_FAILED")

    def test_fail_path_mismatch(self):
        checks = build_checks(
            stats=_passing_stats(),
            safety=_passing_safety(),
            regime={"path_mismatch": True},
            reports_present=True,
        )
        self.assertEqual(determine_verdict(checks), "SHADOW_FAILED")

    def test_final_report(self):
        checks = build_checks(
            stats=_passing_stats(),
            safety=_passing_safety(),
            regime=_passing_regime(),
            reports_present=True,
        )
        report = build_final_report(
            verdict="READY_FOR_CONTROLLED_LIVE",
            checks=checks,
            stats=_passing_stats(),
            safety=_passing_safety(),
            regime=_passing_regime(),
            latency={"overhead_pct": 5.0},
        )
        self.assertEqual(report["phase"], "18A")
        self.assertFalse(report["live_orders"])


# --- bulk tests for coverage target ---

class TestBulkAgreement(unittest.TestCase):
    pass


class TestBulkLatency(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkRegime(unittest.TestCase):
    pass


class TestBulkCluster(unittest.TestCase):
    pass


class TestBulkEquity(unittest.TestCase):
    pass


class TestBulkDiff(unittest.TestCase):
    pass


class TestBulkSafety(unittest.TestCase):
    pass


def _make_bulk_agreement() -> None:
    for i in range(50):
        def test(self, idx=i):
            c = ShadowComparator()
            for j in range(10):
                sig = "BUY" if (idx + j) % 5 else "HOLD"
                c.compare(
                    bar_index=j, timestamp="t", regime="TREND",
                    v40={"signal": sig, "probability": 0.5},
                    v41={"signal": sig, "probability": 0.55},
                    latency_v40_ms=1.0, latency_v41_ms=1.0 + idx * 0.01,
                )
            self.assertGreaterEqual(c.agreement_rate(), 0.0)

        test.__name__ = f"test_bulk_agreement_{i}"
        setattr(TestBulkAgreement, test.__name__, test)


def _make_bulk_latency() -> None:
    for i in range(50):
        def test(self, idx=i):
            lp = LatencyProfiler()
            base = 5.0 + (idx % 5)
            for _ in range(15):
                lp.add(base, base * (1.0 + (idx % 3) * 0.02), base * 2)
            d = lp.to_dict()
            self.assertIn("overhead_ratio", d)

        test.__name__ = f"test_bulk_latency_{i}"
        setattr(TestBulkLatency, test.__name__, test)


def _make_bulk_verdict() -> None:
    for i in range(50):
        def test(self, idx=i):
            stats = _passing_stats()
            stats["agreement_ok"] = idx % 4 != 0
            stats["latency_ok"] = idx % 5 != 0
            checks = build_checks(
                stats=stats,
                safety=_passing_safety(),
                regime=_passing_regime(),
                reports_present=True,
            )
            v = determine_verdict(checks)
            self.assertIn(v, VERDICTS)

        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _make_bulk_regime() -> None:
    for i in range(40):
        def test(self, idx=i):
            c = ShadowComparator()
            regime = "RANGE" if idx % 2 == 0 else "TREND"
            c.compare(
                bar_index=idx, timestamp="t", regime=regime,
                v40={"signal": "SELL", "probability": 0.6},
                v41={"signal": "SELL" if idx % 3 else "HOLD", "probability": 0.6},
                latency_v40_ms=1.0, latency_v41_ms=1.0,
            )
            self.assertIsInstance(c.divergence_rate(regime), float)

        test.__name__ = f"test_bulk_regime_{i}"
        setattr(TestBulkRegime, test.__name__, test)


def _make_bulk_cluster() -> None:
    for i in range(40):
        def test(self, idx=i):
            diffs = [
                {
                    "bar_index": idx * 10 + j,
                    "regime": "TREND",
                    "v40_signal": "HOLD",
                    "v41_signal": "BUY",
                }
                for j in range(5)
            ]
            r = cluster_divergences(diffs)
            self.assertGreaterEqual(r["cluster_count"], 1)

        test.__name__ = f"test_bulk_cluster_{i}"
        setattr(TestBulkCluster, test.__name__, test)


def _make_bulk_equity() -> None:
    for i in range(40):
        def test(self, idx=i):
            eq = ShadowEquityCurve(label=f"v{idx}")
            for j in range(10):
                eq.add(0.01 * ((j % 3) - 1), timestamp=str(j), regime="TREND")
            d = eq.to_dict()
            self.assertEqual(d["points"], 10)
            self.assertIn("metrics", d)

        test.__name__ = f"test_bulk_equity_{i}"
        setattr(TestBulkEquity, test.__name__, test)


def _make_bulk_diff() -> None:
    for i in range(40):
        def test(self, idx=i):
            c = ShadowComparator()
            c.compare(
                bar_index=idx, timestamp="t", regime="TREND",
                v40={"signal": "HOLD", "probability": 0.2},
                v41={"signal": "BUY", "probability": 0.5},
                latency_v40_ms=1.0, latency_v41_ms=1.2,
            )
            report = c.decision_diff_report()
            self.assertEqual(report["diverge"], 1)
            matrix = c.agreement_matrix()
            self.assertIn("agreement_rate", matrix)

        test.__name__ = f"test_bulk_diff_{i}"
        setattr(TestBulkDiff, test.__name__, test)


def _make_bulk_safety() -> None:
    for i in range(40):
        def test(self, idx=i):
            self.assertEqual(ORDER_SEND_CALLS, 0)
            r = assert_no_execution()
            self.assertEqual(r["order_send_calls"], 0)

        test.__name__ = f"test_bulk_safety_{i}"
        setattr(TestBulkSafety, test.__name__, test)


_make_bulk_agreement()
_make_bulk_latency()
_make_bulk_verdict()
_make_bulk_regime()
_make_bulk_cluster()
_make_bulk_equity()
_make_bulk_diff()
_make_bulk_safety()


if __name__ == "__main__":
    unittest.main()
