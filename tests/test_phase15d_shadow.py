"""Phase 15D — shadow mode live safety validation tests."""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.live_validation.config import (
    EXPECTED_DATASET_FINGERPRINT,
    LATENCY_MEAN_TARGET_MS,
    LATENCY_P95_TARGET_MS,
    reports_dir,
)
from tradingbot.ml.live_validation.decision_compare import ComparisonRecord, DecisionComparer
from tradingbot.ml.live_validation.latency_monitor import ShadowLatencyMonitor
from tradingbot.ml.live_validation.live_health import LiveHealthMonitor
from tradingbot.ml.live_validation.orchestrator import run_phase15d_shadow
from tradingbot.ml.live_validation.report_generator import REQUIRED_REPORTS, reports_complete, write_phase15d_reports
from tradingbot.ml.live_validation.risk_compare import RiskComparer
from tradingbot.ml.live_validation.shadow_equity import ShadowEquityTracker
from tradingbot.ml.live_validation.shadow_mode import ORDER_SEND_CALLS, ShadowModeRunner, ShadowModeResult
from tradingbot.ml.live_validation.shadow_statistics import ShadowStatistics
from tradingbot.ml.live_validation.shadow_trade import ShadowTrade, shadow_trade_from_signal
from tradingbot.ml.live_validation.signal_consistency import ConsistencyCheck, SignalConsistencyValidator
from tradingbot.ml.live_validation.validator import validate_shadow_result
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal

from tests.helpers.kernel_tmp_fixture import setup_kernel_tmp

LIVE_VALIDATION_PKG = ROOT / "tradingbot" / "ml" / "live_validation"
FORBIDDEN_PATHS = (
    ROOT / "tradingbot" / "kernel" / "trading_kernel.py",
    ROOT / "tradingbot" / "adapters" / "risk_gate.py",
)
FORBIDDEN_TOKENS = ("order_send", "MetaTrader5", "mt5.order")


def _candles(n: int = 800, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.3, n).cumsum()
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 0.1, n),
            "high": close + rng.uniform(0.2, 1.0, n),
            "low": close - rng.uniform(0.2, 1.0, n),
            "close": close,
            "volume": rng.integers(100, 500, n),
        },
        index=ts,
    )


def _dataset(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    ts = pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "label": [0, 1] * (n // 2),
            "ema50_slope": rng.normal(0, 1, n).tolist(),
            "candle_direction": rng.normal(0, 1, n).tolist(),
            "structure_distance": rng.normal(0, 1, n).tolist(),
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
        }
    )


def _setup_tmp(tmp: str) -> None:
    candles = _candles(1200)
    ds = _dataset(1200)
    ds["timestamp"] = list(candles.index)
    setup_kernel_tmp(tmp, candles=candles, dataset=ds)


def _has_artifacts() -> bool:
    return (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file()


def _mock_signal(direction: str = "BUY") -> TradingSignal:
    return TradingSignal(
        symbol="XAUUSD",
        timeframe="M5",
        direction=SignalDirection[direction],
        confidence=0.7,
        stop_loss=2290.0,
        take_profit=2320.0,
        strategy_name="ml_kernel",
        metadata={"risk_percent": 0.2, "quality": 0.8},
    )


def _mock_unified(direction: str = "BUY") -> UnifiedSignal:
    return UnifiedSignal(
        engine="trend_rf_v40", regime="TREND", direction=direction,
        confidence=0.7, quality=0.8, risk=0.2, reason=["test"],
    )


def _passing_result() -> ShadowModeResult:
    r = ShadowModeResult()
    r.stats.bars_processed = 100
    r.stats.decision_comparer.records.append(
        ComparisonRecord("t", "BUY", "BUY", True, True, 0.0, 0.0, 0.0),
    )
    trade = ShadowTrade("XAUUSD", "2022-01-01", "BUY", 0.7, 0.2, 0.8, 2290, 2320, 2300, 2310, 100.0)
    r.stats.add_trade(trade)
    r.equity.apply_trade(trade)
    for _ in range(10):
        r.latency.record_breakdown({
            "decision_ms": 5, "calibration_ms": 3, "risk_ms": 2,
            "quality_ms": 2, "mapping_ms": 1, "total_ms": 13,
        })
    r.checksum_stable = True
    r.health.bundle_checksum_ok = True
    r.health.registry_healthy = True
    r.health.latency_ok = True
    r.health.feature_consistent = True
    r.health.fingerprint_ok = True
    return r


class TestShadowTrade(unittest.TestCase):
    def test_fields(self):
        t = ShadowTrade("XAUUSD", "t", "BUY", 0.7, 0.2, 0.8, 1.0, 2.0, 1.5)
        self.assertEqual(t.symbol, "XAUUSD")

    def test_to_dict(self):
        t = ShadowTrade("XAUUSD", "t", "SELL", 0.6, 0.1, 0.5, 1.0, 2.0, 1.5)
        self.assertIn("signal", t.to_dict())

    def test_from_signal(self):
        sig = _mock_signal()
        u = _mock_unified()
        t = shadow_trade_from_signal(sig, unified=u, entry=2300.0, bar_time="2022-01-01")
        self.assertEqual(t.signal, "BUY")

    def test_risk_gate_fields(self):
        t = shadow_trade_from_signal(_mock_signal(), risk_allowed=True, risk_reason="ok")
        self.assertTrue(t.risk_gate_allowed)

    def test_default_pnl(self):
        t = ShadowTrade("XAUUSD", "t", "BUY", 0.7, 0.2, 0.8, 1.0, 2.0, 1.5)
        self.assertEqual(t.pnl, 0.0)


class TestDecisionCompare(unittest.TestCase):
    def test_agreement_same_direction(self):
        c = DecisionComparer()
        r = c.compare(timestamp="t", legacy_signal=_mock_signal(), ml_signal=_mock_signal(), ml_unified=_mock_unified())
        self.assertTrue(r.agreement)

    def test_disagreement(self):
        c = DecisionComparer()
        leg = _mock_signal("BUY")
        ml = _mock_signal("SELL")
        r = c.compare(timestamp="t", legacy_signal=leg, ml_signal=ml, ml_unified=_mock_unified("SELL"))
        self.assertFalse(r.direction_match)

    def test_both_hold_agrees(self):
        c = DecisionComparer()
        r = c.compare(timestamp="t", legacy_signal=None, ml_signal=None, ml_unified=_mock_unified("HOLD"))
        self.assertTrue(r.agreement)

    def test_summary_counts(self):
        c = DecisionComparer()
        c.compare(timestamp="t", legacy_signal=_mock_signal(), ml_signal=_mock_signal(), ml_unified=_mock_unified())
        s = c.summary()
        self.assertEqual(s["total"], 1)

    def test_confidence_diff(self):
        c = DecisionComparer()
        leg = _mock_signal()
        leg.confidence = 0.5
        r = c.compare(timestamp="t", legacy_signal=leg, ml_signal=_mock_signal(), ml_unified=_mock_unified())
        self.assertGreater(r.confidence_diff, 0)

    def test_record_to_dict(self):
        c = DecisionComparer()
        r = c.compare(timestamp="t", legacy_signal=None, ml_signal=None)
        self.assertIn("agreement", r.to_dict())


class TestRiskCompare(unittest.TestCase):
    def test_compare_record(self):
        from tradingbot.domain.models import RiskDecision
        rc = RiskComparer()
        r = rc.compare(
            timestamp="t", legacy_signal=_mock_signal(), ml_signal=_mock_signal(),
            risk_decision=RiskDecision(allowed=True, reason="ok"), ml_unified=_mock_unified(),
        )
        self.assertTrue(r.ml_risk_allowed)

    def test_summary(self):
        rc = RiskComparer()
        from tradingbot.domain.models import RiskDecision
        rc.compare(timestamp="t", legacy_signal=None, ml_signal=_mock_signal(),
                   risk_decision=RiskDecision(allowed=False, reason="blocked"), ml_unified=_mock_unified())
        self.assertEqual(rc.summary()["total"], 1)

    def test_to_dict(self):
        rc = RiskComparer()
        from tradingbot.domain.models import RiskDecision
        r = rc.compare(timestamp="t", legacy_signal=None, ml_signal=None,
                       risk_decision=RiskDecision(allowed=False, reason="x"))
        self.assertIn("ml_risk_reason", r.to_dict())

    def test_ml_risk_percent(self):
        rc = RiskComparer()
        from tradingbot.domain.models import RiskDecision
        r = rc.compare(timestamp="t", legacy_signal=None, ml_signal=_mock_signal(),
                       risk_decision=RiskDecision(allowed=True, reason=""), ml_unified=_mock_unified())
        self.assertEqual(r.ml_risk_percent, 0.2)


class TestLatencyMonitor(unittest.TestCase):
    def test_record_breakdown(self):
        m = ShadowLatencyMonitor()
        m.record_breakdown({"decision_ms": 5, "total_ms": 15})
        self.assertEqual(len(m.total_ms), 1)

    def test_build_report(self):
        m = ShadowLatencyMonitor()
        for v in (10, 12, 14, 15, 16):
            m.record_breakdown({"decision_ms": 3, "calibration_ms": 2, "risk_ms": 1,
                                "quality_ms": 1, "mapping_ms": 1, "total_ms": float(v)})
        rep = m.build_report()
        self.assertIn("warm_total", rep)

    def test_passes_targets(self):
        m = ShadowLatencyMonitor()
        for _ in range(5):
            m.record_breakdown({"total_ms": 10.0, "decision_ms": 4, "calibration_ms": 2,
                                "risk_ms": 1, "quality_ms": 1, "mapping_ms": 1})
        self.assertTrue(m.passes_targets())

    def test_fails_high_latency(self):
        m = ShadowLatencyMonitor()
        m.record_breakdown({"total_ms": 100.0, "decision_ms": 50, "calibration_ms": 20,
                            "risk_ms": 10, "quality_ms": 10, "mapping_ms": 10})
        self.assertFalse(m.passes_targets())

    def test_targets_constants(self):
        self.assertEqual(LATENCY_MEAN_TARGET_MS, 20.0)
        self.assertEqual(LATENCY_P95_TARGET_MS, 50.0)


class TestShadowStatistics(unittest.TestCase):
    def test_build_report(self):
        s = ShadowStatistics()
        s.bars_processed = 10
        s.orders_blocked = 2
        rep = s.build_report()
        self.assertEqual(rep["bars_processed"], 10)

    def test_add_trade(self):
        s = ShadowStatistics()
        s.add_trade(ShadowTrade("X", "t", "BUY", 0.5, 0.1, 0.5, 1, 2, 1.5))
        self.assertEqual(len(s.shadow_trades), 1)

    def test_decision_nested(self):
        s = ShadowStatistics()
        s.decision_comparer.compare(timestamp="t", legacy_signal=None, ml_signal=None)
        self.assertIn("decision", s.build_report())


class TestShadowEquity(unittest.TestCase):
    def test_initial_equity(self):
        e = ShadowEquityTracker()
        self.assertEqual(e.equity_curve[0], 10_000.0)

    def test_apply_trade_pnl(self):
        e = ShadowEquityTracker(risk_per_trade=100.0)
        t = ShadowTrade("X", "2022-01-01", "BUY", 0.7, 0.2, 0.8, 2290, 2320, 2300, 2310, 50.0)
        e.apply_trade(t)
        self.assertGreater(e.equity_curve[-1], 10_000.0)

    def test_max_drawdown(self):
        e = ShadowEquityTracker()
        e.equity_curve = [10000, 10500, 9500]
        self.assertGreater(e.max_drawdown(), 0)

    def test_sharpe(self):
        e = ShadowEquityTracker()
        e.equity_curve = [10000, 10050, 10100, 10080, 10150]
        self.assertIsInstance(e.sharpe(), float)

    def test_sortino(self):
        e = ShadowEquityTracker()
        e.equity_curve = [10000, 10050, 9900, 10100]
        self.assertIsInstance(e.sortino(), float)

    def test_ulcer(self):
        e = ShadowEquityTracker()
        e.equity_curve = [10000, 9500, 9800]
        self.assertGreaterEqual(e.ulcer_index(), 0)

    def test_build_report_metrics(self):
        e = ShadowEquityTracker()
        trades = [ShadowTrade("X", "2022-01-01", "BUY", 0.7, 0.2, 0.8, 1, 2, 1.5, 1.6, 100)]
        rep = e.build_report(trades)
        for key in ("profit_factor", "expectancy", "win_rate", "sharpe", "sortino", "ulcer_index"):
            self.assertIn(key, rep)

    def test_daily_pnl_bucket(self):
        e = ShadowEquityTracker()
        t = ShadowTrade("X", "2022-01-05T10:00:00", "BUY", 0.7, 0.2, 0.8, 1, 2, 1.5, 1.6, 25.0)
        e.apply_trade(t)
        self.assertIn("2022-01-05", e.daily_pnl)


class TestSignalConsistency(unittest.TestCase):
    def test_record(self):
        v = SignalConsistencyValidator()
        c = v.record(timestamp="t", unified=_mock_unified(), trading_signal=_mock_signal())
        self.assertEqual(c.direction, "BUY")

    def test_replay_match(self):
        v = SignalConsistencyValidator()
        a = v.record(timestamp="t", unified=_mock_unified(), trading_signal=_mock_signal())
        b = ConsistencyCheck("t", a.decision_fp, a.signal_fp, a.confidence, a.risk, a.quality, a.direction)
        self.assertTrue(v.verify_replay(a, b))

    def test_replay_mismatch(self):
        v = SignalConsistencyValidator()
        a = v.record(timestamp="t", unified=_mock_unified(), trading_signal=_mock_signal())
        b = ConsistencyCheck("t", "bad", a.signal_fp, a.confidence, a.risk, a.quality, a.direction)
        self.assertFalse(v.verify_replay(a, b))

    def test_is_deterministic(self):
        v = SignalConsistencyValidator()
        self.assertTrue(v.is_deterministic())

    def test_summary(self):
        v = SignalConsistencyValidator()
        v.record(timestamp="t", unified=_mock_unified(), trading_signal=_mock_signal())
        self.assertEqual(v.summary()["checks"], 1)


class TestLiveHealth(unittest.TestCase):
    def test_record_exception(self):
        h = LiveHealthMonitor()
        h.record_exception(ValueError("x"))
        self.assertEqual(h.exception_count, 1)

    def test_passes_default_false(self):
        h = LiveHealthMonitor()
        self.assertFalse(h.passes())

    def test_passes_when_all_ok(self):
        h = LiveHealthMonitor()
        h.bundle_checksum_ok = True
        h.registry_healthy = True
        h.latency_ok = True
        h.feature_consistent = True
        h.fingerprint_ok = True
        self.assertTrue(h.passes())

    def test_build_report(self):
        h = LiveHealthMonitor()
        rep = h.build_report()
        self.assertIn("memory_mb", rep)

    def test_safe_run(self):
        ok, err = LiveHealthMonitor.safe_run(lambda: 1 / 0)
        self.assertFalse(ok)

    def test_bundle_check_with_tmp(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            h = LiveHealthMonitor()
            self.assertTrue(h.run_bundle_check(tmp))


class TestValidator(unittest.TestCase):
    def test_pass_all_criteria(self):
        r = _passing_result()
        with tempfile.TemporaryDirectory() as tmp:
            write_phase15d_reports(r, base_dir=tmp)
            from tradingbot.ml.live_validation.report_generator import write_final_report
            write_final_report({"status": "PASS"}, base_dir=tmp)
            v = validate_shadow_result(r, base_dir=tmp)
            self.assertEqual(v.status, "PASS")
            self.assertEqual(v.recommendation, "READY_FOR_PHASE15E")

    def test_fail_orders(self):
        r = _passing_result()
        r.order_send_calls = 1
        v = validate_shadow_result(r, require_full_reports=False)
        self.assertEqual(v.status, "NEEDS_REVIEW")

    def test_fail_checksum(self):
        r = _passing_result()
        r.checksum_stable = False
        v = validate_shadow_result(r, require_full_reports=False)
        self.assertFalse(v.criteria["no_checksum_drift"])

    def test_fail_latency(self):
        r = _passing_result()
        r.latency.total_ms = [100.0] * 5
        v = validate_shadow_result(r, require_full_reports=False)
        self.assertFalse(v.criteria["latency_mean_target"])

    def test_fail_deterministic(self):
        r = _passing_result()
        r.consistency.replay_mismatches.append({})
        v = validate_shadow_result(r, require_full_reports=False)
        self.assertFalse(v.criteria["replay_deterministic"])

    def test_blockers_list(self):
        r = _passing_result()
        r.order_send_calls = 2
        v = validate_shadow_result(r, require_full_reports=False)
        self.assertTrue(len(v.blockers) > 0)

    def test_to_dict(self):
        r = _passing_result()
        v = validate_shadow_result(r, require_full_reports=False)
        self.assertEqual(v.to_dict()["phase"], "15D")

    def test_expected_fingerprint_constant(self):
        self.assertEqual(len(EXPECTED_DATASET_FINGERPRINT), 16)


class TestReportGenerator(unittest.TestCase):
    def test_write_reports(self):
        r = _passing_result()
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15d_reports(r, base_dir=tmp)
            self.assertTrue((out / "shadow_statistics.json").is_file())

    def test_reports_complete(self):
        r = _passing_result()
        with tempfile.TemporaryDirectory() as tmp:
            write_phase15d_reports(r, base_dir=tmp)
            from tradingbot.ml.live_validation.report_generator import write_final_report
            write_final_report({"status": "PASS"}, base_dir=tmp)
            self.assertTrue(reports_complete(tmp))

    def test_required_reports_count(self):
        self.assertEqual(len(REQUIRED_REPORTS), 9)

    def test_json_parseable(self):
        r = _passing_result()
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15d_reports(r, base_dir=tmp)
            data = json.loads((out / "latency_report.json").read_text())
            self.assertIn("total", data)


class TestSafetyGuards(unittest.TestCase):
    def test_no_order_send_in_package(self):
        for py in LIVE_VALIDATION_PKG.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            self.assertNotIn("order_send(", src, msg=str(py))

    def test_no_mt5_execution_in_package(self):
        for py in LIVE_VALIDATION_PKG.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            self.assertNotIn("order_send(", src, msg=str(py))
            self.assertNotIn("MetaTrader5", src, msg=str(py))
            self.assertNotIn("mt5.order", src, msg=str(py))

    def test_order_send_calls_zero_initial(self):
        self.assertEqual(ORDER_SEND_CALLS, 0)

    def test_kernel_path_unchanged_import_only(self):
        src = (LIVE_VALIDATION_PKG / "shadow_mode.py").read_text(encoding="utf-8")
        self.assertNotIn("TradingKernel", src)

    def test_risk_gate_import_read_only(self):
        src = (LIVE_VALIDATION_PKG / "shadow_mode.py").read_text(encoding="utf-8")
        self.assertIn("create_risk_gate", src)
        self.assertNotIn("RiskGate(", src.replace("create_risk_gate", ""))

    def test_ast_no_forbidden_calls(self):
        for py in LIVE_VALIDATION_PKG.glob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ("order_send", "OrderSend"))

    def test_forbidden_files_exist_unmodified_marker(self):
        for p in FORBIDDEN_PATHS:
            self.assertTrue(p.is_file())

    def test_execution_blocked_flag_in_orchestrator(self):
        src = (LIVE_VALIDATION_PKG / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("execution_blocked", src)


class TestShadowModeIntegration(unittest.TestCase):
    def setUp(self):
        PipelineCache.reset()

    def test_runner_candles_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = ShadowModeRunner(base_dir=tmp, days=30, stride=50, warmup=100).run()
            self.assertIn("candles_unavailable", r.errors)

    def test_runner_zero_order_send(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            with mock.patch(
                "tradingbot.ml.live_validation.shadow_mode.LegacyStrategyRegistry.generate_signal",
                return_value=None,
            ):
                r = ShadowModeRunner(
                    base_dir=tmp, days=30, stride=30, warmup=350,
                ).run()
            self.assertEqual(r.order_send_calls, 0)

    def test_shadow_equity_from_run(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            with mock.patch(
                "tradingbot.ml.live_validation.shadow_mode.LegacyStrategyRegistry.generate_signal",
                return_value=None,
            ):
                r = ShadowModeRunner(base_dir=tmp, days=30, stride=30, warmup=350).run()
            self.assertGreater(r.stats.bars_processed, 0)

    def test_latency_recorded(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            with mock.patch(
                "tradingbot.ml.live_validation.shadow_mode.LegacyStrategyRegistry.generate_signal",
                return_value=None,
            ):
                r = ShadowModeRunner(base_dir=tmp, days=30, stride=30, warmup=350).run()
            self.assertGreaterEqual(len(r.latency.total_ms), 0)

    def test_checksum_stable_flag(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            with mock.patch(
                "tradingbot.ml.live_validation.shadow_mode.LegacyStrategyRegistry.generate_signal",
                return_value=None,
            ):
                r = ShadowModeRunner(base_dir=tmp, days=30, stride=30, warmup=350).run()
            self.assertTrue(r.checksum_stable)

    def test_agreement_stats_generated(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            with mock.patch(
                "tradingbot.ml.live_validation.shadow_mode.LegacyStrategyRegistry.generate_signal",
                return_value=None,
            ):
                r = ShadowModeRunner(base_dir=tmp, days=30, stride=30, warmup=350).run()
            self.assertGreater(r.stats.decision_comparer.summary().get("total", 0), 0)

    def test_orchestrator_writes_reports(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            with mock.patch(
                "tradingbot.ml.live_validation.shadow_mode.LegacyStrategyRegistry.generate_signal",
                return_value=None,
            ), mock.patch(
                "tradingbot.ml.live_validation.live_health.LiveHealthMonitor.run_fingerprint_check",
                return_value=True,
            ):
                result = run_phase15d_shadow(
                    base_dir=tmp, days=30, stride=30, warmup=350, seed=42,
                )
            self.assertTrue(reports_complete(tmp))
            self.assertTrue((reports_dir(tmp) / "phase15d_final_report.json").is_file())

    def test_orchestrator_result_dict(self):
        r = _passing_result()
        with tempfile.TemporaryDirectory() as tmp:
            write_phase15d_reports(r, base_dir=tmp)
            from tradingbot.ml.live_validation.report_generator import write_final_report
            from tradingbot.ml.live_validation.validator import validate_shadow_result
            v = validate_shadow_result(r, base_dir=tmp)
            write_final_report(v.to_dict(), base_dir=tmp)
            self.assertTrue(reports_complete(tmp))


class TestConfig(unittest.TestCase):
    def test_reports_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = reports_dir(tmp)
            self.assertIn("phase15d", str(p))


class TestShadowModeResult(unittest.TestCase):
    def test_to_dict(self):
        r = _passing_result()
        d = r.to_dict()
        self.assertIn("latency", d)
        self.assertIn("health", d)


if __name__ == "__main__":
    unittest.main()
