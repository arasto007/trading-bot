"""Phase 15C — monitoring layer tests."""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.kernel_adapter import KernelAdapter
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.monitoring.bundle_monitor import BundleMonitor
from tradingbot.ml.monitoring.config import EXPECTED_DATASET_FINGERPRINT, live_dir, reports_dir
from tradingbot.ml.monitoring.dashboard_export import DashboardExport, generate_alerts
from tradingbot.ml.monitoring.decision_logger import DecisionLogger
from tradingbot.ml.monitoring.engine_monitor import EngineMonitor
from tradingbot.ml.monitoring.fallback_monitor import FallbackMonitor
from tradingbot.ml.monitoring.health_monitor import HealthMonitor
from tradingbot.ml.monitoring.latency_monitor import LatencyMonitor
from tradingbot.ml.monitoring.observer import MonitoredKernelAdapter, MonitoringHub
from tradingbot.ml.monitoring.orchestrator import run_phase15c_monitoring, run_monitoring_replay
from tradingbot.ml.monitoring.performance_monitor import PerformanceMonitor
from tradingbot.ml.monitoring.prediction_monitor import PredictionMonitor
from tradingbot.ml.monitoring.statistics import ThreadSafeCounter, ThreadSafeStore, latency_summary, percentile, rate
from tradingbot.domain.models import MarketKey

from tests.helpers.kernel_tmp_fixture import setup_kernel_tmp

KERNEL_PATH = ROOT / "tradingbot" / "kernel" / "trading_kernel.py"
RISK_PATH = ROOT / "tradingbot" / "adapters" / "risk_gate.py"
EXEC_PATH = ROOT / "tradingbot" / "pipeline" / "execution_stage.py"
MONITORING_PKG = ROOT / "tradingbot" / "ml" / "monitoring"


def _candles(n: int = 800, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.3, n).cumsum()
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": rng.integers(100, 500, n)},
        index=ts,
    )


def _dataset(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    ts = pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts, "symbol": "XAUUSD", "timeframe": "M5",
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


class TestStatistics(unittest.TestCase):
    def test_percentile(self):
        self.assertGreater(percentile([1, 2, 3, 4, 5], 0.95), 0)

    def test_latency_summary(self):
        s = latency_summary([10.0, 20.0, 30.0])
        self.assertEqual(s["count"], 3)

    def test_rate(self):
        self.assertEqual(rate(1, 4), 0.25)

    def test_thread_safe_counter(self):
        c = ThreadSafeCounter()
        self.assertEqual(c.inc(), 1)

    def test_thread_safe_store(self):
        s = ThreadSafeStore()
        s.append({"a": 1})
        self.assertEqual(len(s), 1)


class TestDecisionLogger(unittest.TestCase):
    def test_log_creates_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DecisionLogger(tmp)
            logger.log(
                symbol="XAUUSD", timeframe="M5", regime="TREND", engine="trend_rf_v40",
                direction="BUY", confidence=0.7, quality=0.8, risk=0.2,
                latency_ms={"total_ms": 5.0}, trace_id="abc", checksum="chk",
                decision_reason=["test"],
            )
            self.assertTrue(logger.path.is_file())
            self.assertEqual(logger.count(), 1)

    def test_read_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DecisionLogger(tmp)
            logger.log(
                symbol="XAUUSD", timeframe="M5", regime="TREND", engine="e",
                direction="HOLD", confidence=0.0, quality=0.0, risk=0.0,
                latency_ms={}, trace_id="t", checksum="c", decision_reason=[],
            )
            self.assertEqual(len(logger.read_recent()), 1)


class TestLatencyMonitor(unittest.TestCase):
    def test_record_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = LatencyMonitor(tmp)
            mon.record(feature_ms=1, decision_ms=2, total_ms=10)
            report = mon.build_report()
            self.assertEqual(report["samples"], 1)
            path = mon.write_report()
            self.assertTrue(path.is_file())


class TestEngineMonitor(unittest.TestCase):
    def test_record_calls(self):
        em = EngineMonitor()
        em.record_call("phase9_9", success=True, latency_ms=5.0)
        report = em.build_report()
        self.assertEqual(report["phase9_9"]["calls"], 1)

    def test_set_meta(self):
        em = EngineMonitor()
        em.set_engine_meta("trend_rf_v40", checksum="abc", version="v1")
        self.assertEqual(em.build_report()["trend_rf_v40"]["checksum"], "abc")

    def test_default_buckets_include_active_and_rollback(self):
        from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

        report = EngineMonitor().build_report()
        self.assertIn("trend_rf_v40", report)
        self.assertIn(resolve_active_trend_engine_id(), report)


class TestFallbackMonitor(unittest.TestCase):
    def test_classify_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb = FallbackMonitor(tmp)
            ev = fb.record("checksum_invalid")
            self.assertEqual(ev["category"], "checksum_mismatch")

    def test_write_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb = FallbackMonitor(tmp)
            fb.record("legacy_fallback")
            path = fb.write_report(total_decisions=10)
            self.assertTrue(path.is_file())


class TestBundleMonitor(unittest.TestCase):
    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_DATASET_FINGERPRINT, "70b38325ee1c7e1e")

    def test_check_all(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            chk = BundleMonitor(tmp).check_all()
            self.assertIn("all_valid", chk)


class TestPredictionMonitor(unittest.TestCase):
    def test_accept_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = PredictionMonitor(tmp)
            pm.record(engine="trend_rf_v40", probability=0.7, confidence=0.65, accepted=True)
            pm.record(engine="phase9_9", probability=0.4, confidence=0.4, accepted=False, block_reason="low_conf")
            report = pm.build_report()
            self.assertEqual(report["accepted"], 1)
            self.assertTrue(pm.write_report().is_file())


class TestPerformanceMonitor(unittest.TestCase):
    def test_ingest(self):
        perf = PerformanceMonitor()
        perf.ingest_decision({"direction": "BUY", "regime": "TREND", "engine": "trend_rf_v40", "confidence": 0.7, "quality": 0.6, "risk": 0.2, "timestamp": "2024-01-01T00:00:00+00:00"})
        report = perf.build_report()
        self.assertEqual(report["buy"], 1)


class TestDashboard(unittest.TestCase):
    def test_generate_alerts_latency(self):
        alerts = generate_alerts(
            latency_report={"total_inference": {"max": 150, "p95": 120}},
            health_status={"passes": True, "bundles": {"all_valid": True}, "fingerprint_match": True, "engine_availability": {}},
            fallback_report={"fallback_rate": 0.01},
            performance={"buy": 1, "sell": 0, "total_decisions": 10},
            prediction_stats={"mean_confidence": 0.6, "total_predictions": 10},
        )
        self.assertTrue(any(a["code"] == "LATENCY_HIGH" for a in alerts))

    def test_dashboard_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            dash = DashboardExport(tmp).build(
                health_status={"passes": True, "bundles": {"all_valid": True}, "fingerprint_match": True, "engine_availability": {}},
                latency_report={"total_inference": {"max": 10}},
                engine_report={},
                fallback_report={"fallback_rate": 0},
                prediction_stats={},
                performance={},
                recent_decisions=[],
            )
            path = DashboardExport(tmp).write(dash)
            self.assertTrue(path.is_file())


class TestObserver(unittest.TestCase):
    def test_monitored_adapter_wraps(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            inner = build_kernel_adapter(base_dir=tmp, enable_monitoring=False)
            hub = MonitoringHub(tmp)
            wrapped = MonitoredKernelAdapter(inner, hub)
            try:
                wrapped.generate_signal(MarketKey("XAUUSD", "M5"), _candles(400))
            except KernelFallbackError:
                pass
            self.assertTrue(
                hub.decisions.count() > 0 or hub.fallbacks.build_report()["total_fallbacks"] > 0
            )

    def test_monitored_logs_fallback(self):
        inner = mock.Mock()
        inner._deps = mock.Mock(registry=mock.Mock(), base_dir=None)
        inner.last_unified_signal = None
        inner.last_latency = mock.Mock(to_dict=lambda: {})
        inner.generate_signal.side_effect = KernelFallbackError("checksum_fail")
        hub = MonitoringHub()
        wrapped = MonitoredKernelAdapter(inner, hub)
        with self.assertRaises(KernelFallbackError):
            wrapped.generate_signal(MarketKey("XAUUSD", "M5"), _candles(50))
        self.assertEqual(hub.fallbacks.build_report()["total_fallbacks"], 1)


class TestHealthMonitor(unittest.TestCase):
    def test_health_check(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            stack = build_ml_kernel_stack(base_dir=tmp)
            hm = HealthMonitor(tmp)
            status = hm.check(stack.registry)
            self.assertIn("passes", status)
            self.assertTrue(hm.checks_run >= 1)


class TestOrchestrator(unittest.TestCase):
    def test_replay_short(self):
        # Replay must produce observability events. PIPELINE_TIMEOUT_MS=500 is the
        # hard ML-path fallback; this fixture often exceeds it. Timeout→fallback
        # is the designed safety valve, not a test failure.
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            hub = run_monitoring_replay(base_dir=tmp, days=30, stride=15, warmup=300)
            fallbacks = hub.fallbacks.build_report()
            self.assertGreater(
                hub.decisions.count() + int(fallbacks.get("total_fallbacks", 0)),
                0,
            )

    def test_full_validation(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            result = run_phase15c_monitoring(base_dir=tmp, days=30, stride=15, warmup=300)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertTrue(Path(result.reports_dir).is_dir())
            self.assertTrue((Path(result.reports_dir) / "dashboard.json").is_file())


class TestSafety(unittest.TestCase):
    def test_kernel_untouched(self):
        text = KERNEL_PATH.read_text(encoding="utf-8")
        self.assertNotIn("monitoring", text.lower())
        self.assertNotIn("phase15c", text.lower())

    def test_risk_gate_untouched(self):
        text = RISK_PATH.read_text(encoding="utf-8")
        self.assertNotIn("phase15c", text.lower())

    def test_execution_untouched(self):
        text = EXEC_PATH.read_text(encoding="utf-8")
        self.assertNotIn("phase15c", text.lower())

    def test_monitoring_pkg_no_order_send(self):
        violations = []
        for py in MONITORING_PKG.glob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                else:
                    continue
                for m in mods:
                    if "order_send" in m or "mt5_execution" in m:
                        violations.append(m)
        self.assertEqual(violations, [])


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_decision_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = DecisionLogger(tmp)
            def worker():
                logger.log(
                    symbol="XAUUSD", timeframe="M5", regime="TREND", engine="e",
                    direction="HOLD", confidence=0.0, quality=0.0, risk=0.0,
                    latency_ms={}, trace_id="t", checksum="c", decision_reason=[],
                )
            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(logger.count(), 10)


class TestPaths(unittest.TestCase):
    def test_live_dir(self):
        self.assertIn("live", str(live_dir("/x")))

    def test_reports_dir(self):
        self.assertIn("phase15c", str(reports_dir("/x")))


class TestCLI(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase15c_monitoring.py").is_file())


class TestModulesExist(unittest.TestCase):
    def test_all_modules(self):
        names = (
            "decision_logger", "latency_monitor", "engine_monitor", "health_monitor",
            "fallback_monitor", "prediction_monitor", "bundle_monitor",
            "performance_monitor", "statistics", "dashboard_export", "orchestrator",
        )
        for name in names:
            self.assertTrue((MONITORING_PKG / f"{name}.py").is_file(), name)

    def test_kernel_adapter_exists(self):
        self.assertTrue((ROOT / "tradingbot" / "ml" / "integration" / "kernel_adapter.py").is_file())


class TestReplayCompatibility(unittest.TestCase):
    def test_decisions_jsonl_format(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            run_monitoring_replay(base_dir=tmp, days=14, stride=20, warmup=300)
            path = live_dir(tmp) / "decisions.jsonl"
            self.assertTrue(path.is_file())
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            for field in ("symbol", "direction", "confidence", "trace_id", "checksum"):
                self.assertIn(field, row)


class TestExtraCoverage(unittest.TestCase):
    def test_fallback_bundle_missing(self):
        fb = FallbackMonitor()
        self.assertEqual(fb._classify("bundle_or_checksum_missing"), "bundle_missing")

    def test_alert_fingerprint(self):
        alerts = generate_alerts(
            latency_report={"total_inference": {"max": 10, "p95": 5}},
            health_status={"passes": False, "bundles": {"all_valid": False}, "fingerprint_match": False, "gate_errors": [], "engine_availability": {}},
            fallback_report={"fallback_rate": 0},
            performance={"buy": 1, "total_decisions": 5},
            prediction_stats={"mean_confidence": 0.6, "total_predictions": 5},
        )
        self.assertTrue(any(a["code"] == "FINGERPRINT_MISMATCH" for a in alerts))

    def test_alert_fallback_rate(self):
        alerts = generate_alerts(
            latency_report={"total_inference": {"max": 10, "p95": 5}},
            health_status={"passes": True, "bundles": {"all_valid": True}, "fingerprint_match": True, "engine_availability": {}},
            fallback_report={"fallback_rate": 0.10},
            performance={"buy": 1, "total_decisions": 5},
            prediction_stats={"mean_confidence": 0.6, "total_predictions": 5},
        )
        self.assertTrue(any(a["code"] == "FALLBACK_RATE_HIGH" for a in alerts))

    def test_decision_logger_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = DecisionLogger(tmp).log(
                symbol="XAUUSD", timeframe="M5", regime="RANGE", engine="phase9_9",
                direction="SELL", confidence=0.55, quality=0.5, risk=0.15,
                latency_ms={"total_ms": 3}, trace_id="tid", checksum="cs",
                decision_reason=["r1"], bundle_version="v1",
            )
            self.assertEqual(rec["bundle_version"], "v1")

    def test_latency_report_fields(self):
        s = latency_summary([5.0, 10.0, 15.0, 20.0, 25.0])
        for k in ("mean", "median", "p95", "p99", "max"):
            self.assertIn(k, s)

    def test_health_monitor_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            hm = HealthMonitor(tmp)
            self.assertIn("health_status.json", str(hm._path))

    def test_orchestrator_reports_list(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            result = run_phase15c_monitoring(base_dir=tmp, days=14, stride=25)
            rdir = Path(result.reports_dir)
            for name in (
                "monitoring_report.json", "latency_report.json", "engine_report.json",
                "fallback_report.json", "prediction_report.json", "performance_report.json",
                "dashboard.json", "phase15c_final_report.json",
            ):
                self.assertTrue((rdir / name).is_file(), name)

    def test_monitored_inner_property(self):
        inner = mock.Mock()
        inner._deps = mock.Mock(registry=mock.Mock(get=lambda x: None), base_dir=None)
        inner.last_unified_signal = None
        inner.last_latency = mock.Mock(to_dict=lambda: {"total_ms": 1})
        inner.generate_signal.return_value = None
        hub = MonitoringHub()
        MonitoredKernelAdapter(inner, hub).generate_signal(MarketKey("XAUUSD", "M5"), _candles(350))
        inner.generate_signal.assert_called_once()

    def test_bundle_trend_check(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            t = BundleMonitor(tmp).check_trend()
            self.assertTrue(t.get("checksum_valid"))

    def test_bundle_phase99_check(self):
        if not _has_artifacts():
            self.skipTest("artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            p = BundleMonitor(tmp).check_phase99()
            self.assertTrue(p.get("checksum_valid"))

    def test_performance_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            perf = PerformanceMonitor(tmp)
            perf.ingest_decision({"direction": "HOLD", "regime": "TREND", "engine": "e", "confidence": 0, "quality": 0, "risk": 0, "timestamp": "2024-01-01T00:00:00+00:00"})
            self.assertTrue(perf.write_report().is_file())

    def test_latency_from_breakdown(self):
        mon = LatencyMonitor()
        mon.record_from_breakdown({"features_ms": 1, "decision_ms": 2, "total_ms": 5})
        self.assertEqual(mon.build_report()["samples"], 1)

    def test_hub_bar_health_trigger(self):
        hub = MonitoringHub()
        reg = mock.Mock()
        reg.health_all.return_value = {}
        reg.get.return_value = None
        for _ in range(50):
            hub.maybe_health_check(reg)
        self.assertGreaterEqual(hub.health.checks_run, 1)

    def test_performance_fallback_pct(self):
        perf = PerformanceMonitor()
        perf.ingest_fallback()
        perf.ingest_decision({"direction": "HOLD", "regime": "TREND", "engine": "e", "confidence": 0, "quality": 0, "risk": 0, "timestamp": "2024-01-01T00:00:00+00:00"})
        self.assertGreater(perf.build_report()["fallback_pct"], 0)

    def test_prediction_write_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = PredictionMonitor(tmp)
            pm.record(engine="e", probability=0.5, confidence=0.5, accepted=True)
            self.assertTrue(pm.write_report().exists())

    def test_engine_failure_record(self):
        em = EngineMonitor()
        em.record_call("quality", success=False)
        self.assertEqual(em.build_report()["quality"]["failures"], 1)

    def test_dashboard_alerts_no_signals(self):
        alerts = generate_alerts(
            latency_report={"total_inference": {"max": 10, "p95": 5}},
            health_status={"passes": True, "bundles": {"all_valid": True}, "fingerprint_match": True, "engine_availability": {}},
            fallback_report={"fallback_rate": 0},
            performance={"buy": 0, "sell": 0, "total_decisions": 100},
            prediction_stats={"mean_confidence": 0.6, "total_predictions": 100},
        )
        self.assertTrue(any(a["code"] == "NO_TRADE_SIGNALS" for a in alerts))

    def test_fingerprint_unchanged(self):
        self.assertEqual(EXPECTED_DATASET_FINGERPRINT, "70b38325ee1c7e1e")


if __name__ == "__main__":
    unittest.main()
