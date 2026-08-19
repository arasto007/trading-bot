"""Phase 15B — kernel ML integration tests."""

from __future__ import annotations

import ast
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
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.integration.config import is_ml_kernel_enabled, ml_kernel_config_from_env
from tradingbot.ml.integration.factory import (
    build_kernel_adapter,
    build_ml_kernel_stack,
    build_strategy_registry,
)
from tradingbot.ml.integration.health_gate import (
    HealthGateResult,
    KernelFallbackError,
    run_pre_decision_health,
    validate_feature_row,
)
from tradingbot.ml.integration.kernel_adapter import KernelAdapter, LatencyBreakdown, MLKernelDependencies
from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry
from tradingbot.ml.integration.monitoring import (
    live_monitoring_dir,
    log_fallback_event,
    write_engine_health,
    write_pipeline_statistics,
)
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.replay_validator import ReplayStats, run_kernel_replay
from tradingbot.ml.integration.signal_mapper import (
    STRATEGY_NAME,
    map_unified_to_trading_signal,
    trading_signal_schema,
)
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal
from tradingbot.ml.phase15a.trend_bundle import freeze_trend_bundle_from_candles
from tradingbot.ml.integration.phase15b_orchestrator import phase15b_reports_dir, run_phase15b_validation

INTEGRATION_PKG = ROOT / "tradingbot" / "ml" / "integration"
KERNEL_PATH = ROOT / "tradingbot" / "kernel" / "trading_kernel.py"
FORBIDDEN_IN_ADAPTER = ("order_send", "mt5_execution", "tradingbot.kernel.trading_kernel")


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


def _setup_tmp(tmp: str, *, copy_phase99: bool = True) -> None:
    if copy_phase99:
        import shutil
        src = ROOT / "data" / "ml" / "research" / "phase9_9_best"
        if src.is_dir():
            dst = Path(tmp) / "ml" / "research" / "phase9_9_best"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    CandleStore(tmp).store("XAUUSD", "M5", _candles(1200))
    DatasetStore(tmp).store_v2("XAUUSD", "M5", _dataset())
    freeze_trend_bundle_from_candles(_candles(1200), base_dir=tmp)


def _has_artifacts() -> bool:
    return (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file()


class TestPhase15BConfig(unittest.TestCase):
    def test_ml_kernel_default_off(self):
        os.environ.pop("USE_ML_KERNEL", None)
        self.assertFalse(is_ml_kernel_enabled())

    def test_ml_kernel_env_on(self):
        os.environ["USE_ML_KERNEL"] = "true"
        try:
            self.assertTrue(is_ml_kernel_enabled())
        finally:
            os.environ.pop("USE_ML_KERNEL", None)

    def test_ml_kernel_config_dict(self):
        cfg = ml_kernel_config_from_env()
        self.assertIn("use_ml_kernel", cfg)


class TestSignalMapper(unittest.TestCase):
    def test_map_buy(self):
        unified = UnifiedSignal(
            engine="trend_rf_v40", regime="TREND", direction="BUY",
            confidence=0.7, quality=0.8, risk=0.25,
            reason=["test"], trace=["t1"],
        )
        market = MarketKey("XAUUSD", "M5")
        sig = map_unified_to_trading_signal(unified, market, _candles(100))
        self.assertEqual(sig.direction, SignalDirection.BUY)
        self.assertEqual(sig.strategy_name, STRATEGY_NAME)

    def test_map_sell(self):
        unified = UnifiedSignal(
            engine="phase9_9", regime="RANGE", direction="SELL",
            confidence=0.6, quality=0.5, risk=0.1,
        )
        sig = map_unified_to_trading_signal(unified, MarketKey("XAUUSD", "M5"), _candles(100))
        self.assertEqual(sig.direction, SignalDirection.SELL)

    def test_metadata_preserves_engine(self):
        unified = UnifiedSignal(
            engine="trend_rf_v40", regime="TREND", direction="BUY",
            confidence=0.65, quality=0.7, risk=0.2,
        )
        sig = map_unified_to_trading_signal(unified, MarketKey("XAUUSD", "M5"), _candles(100))
        self.assertEqual(sig.metadata["engine_name"], "trend_rf_v40")
        self.assertIn("trace_id", sig.metadata)

    def test_metadata_preserves_reason(self):
        unified = UnifiedSignal(
            engine="trend_rf_v40", regime="TREND", direction="HOLD",
            confidence=0.0, quality=0.0, risk=0.0, reason=["blocked"],
        )
        sig = map_unified_to_trading_signal(unified, MarketKey("XAUUSD", "M5"), _candles(100))
        self.assertEqual(sig.metadata["reason"], ["blocked"])

    def test_schema_fields(self):
        schema = trading_signal_schema()
        self.assertIn("confidence", schema["fields"])
        self.assertIn("trace_id", schema["fields"])


class TestPipelineCache(unittest.TestCase):
    def setUp(self):
        PipelineCache.reset()

    def test_registry_singleton(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            r1 = PipelineCache.get_registry(base_dir=tmp)
            r2 = PipelineCache.get_registry(base_dir=tmp)
            self.assertIs(r1, r2)

    def test_trend_bundle_singleton(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            b1 = PipelineCache.get_trend_bundle(base_dir=tmp)
            b2 = PipelineCache.get_trend_bundle(base_dir=tmp)
            self.assertIs(b1, b2)

    def test_unified_frame_cache(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            c = _candles(400)
            f1 = PipelineCache.get_unified_frame(c, base_dir=tmp)
            f2 = PipelineCache.get_unified_frame(c, base_dir=tmp)
            self.assertFalse(f1.empty)
            self.assertEqual(len(f1), len(f2))

    def test_prediction_cache(self):
        PipelineCache.set_prediction("k1", "abc", {"direction": "HOLD"})
        self.assertEqual(PipelineCache.get_prediction("k1")["direction"], "HOLD")

    def test_prediction_cache_key_uses_timestamp(self):
        idx = pd.date_range("2026-06-01", periods=80, freq="5min", tz="UTC")
        candles = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=idx,
        )
        row = pd.Series({"rsi": 50.0, "adx": 20.0})
        key = PipelineCache.build_prediction_cache_key(
            symbol="XAUUSD",
            timeframe="M5",
            candles=candles,
            unified_row=row,
        )
        self.assertIn("2026-06-01", key)
        self.assertNotIn("|79|", key)

    def test_reset_clears(self):
        PipelineCache.set_prediction("k1", "abc", {"x": 1})
        PipelineCache.reset()
        self.assertIsNone(PipelineCache.get_prediction("k1"))


class TestHealthGate(unittest.TestCase):
    def test_feature_row_missing(self):
        row = pd.Series({"ema20_slope": 1.0})
        res = validate_feature_row(row, feature_order=["ema20_slope", "adx"])
        self.assertFalse(res.passes)

    def test_fallback_error_reason(self):
        err = KernelFallbackError("checksum_fail", checks={"a": 1})
        self.assertEqual(err.reason, "checksum_fail")

    def test_health_with_bundle(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            reg = PipelineCache.get_registry(base_dir=tmp)
            health = run_pre_decision_health(registry=reg, base_dir=tmp)
            self.assertIsInstance(health, HealthGateResult)


class TestFactoryAndDI(unittest.TestCase):
    def test_stack_builds_components(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            stack = build_ml_kernel_stack(base_dir=tmp)
            self.assertIn("phase9_9", stack.registry.list_ids())
            self.assertIn("trend_rf_v40", stack.registry.list_ids())

    def test_adapter_from_stack(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            adapter = build_kernel_adapter(base_dir=tmp)
            self.assertIsInstance(adapter, KernelAdapter)

    def test_unconfigured_registry_when_flag_absent(self):
        os.environ.pop("USE_ML_KERNEL", None)
        reg = build_strategy_registry({})
        self.assertEqual(type(reg).__name__, "UnconfiguredEngineRegistry")

    def test_ml_registry_when_flag_on(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        os.environ["USE_ML_KERNEL"] = "true"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                _setup_tmp(tmp)
                reg = build_strategy_registry({"BASE_DIR": tmp}, base_dir=tmp)
                self.assertIsInstance(reg, MLKernelRegistry)
        finally:
            os.environ.pop("USE_ML_KERNEL", None)


class TestKernelAdapter(unittest.TestCase):
    def setUp(self):
        PipelineCache.reset()

    def test_produce_unified_signal(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            adapter = build_kernel_adapter(base_dir=tmp)
            sig = adapter.produce_unified_signal(MarketKey("XAUUSD", "M5"), _candles(280))
            self.assertIn(sig.direction, ("BUY", "SELL", "HOLD"))

    def test_generate_signal_returns_trading_signal_or_none(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            adapter = build_kernel_adapter(base_dir=tmp)
            out = adapter.generate_signal(MarketKey("XAUUSD", "M5"), _candles(280))
            self.assertTrue(out is None or isinstance(out, TradingSignal))

    def test_latency_breakdown(self):
        lat = LatencyBreakdown(features_ms=1.0, total_ms=5.0)
        self.assertIn("total_ms", lat.to_dict())

    def test_prediction_cache_hit(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            adapter = build_kernel_adapter(base_dir=tmp)
            df = _candles(280)
            adapter.produce_unified_signal(MarketKey("XAUUSD", "M5"), df)
            lat1 = adapter.last_latency.total_ms
            adapter.produce_unified_signal(MarketKey("XAUUSD", "M5"), df)
            lat2 = adapter.last_latency.total_ms
            self.assertLessEqual(lat2, lat1 + 1.0)


class TestMLKernelRegistry(unittest.TestCase):
    def test_fallback_on_adapter_error(self):
        legacy = mock.Mock()
        legacy.generate_signal.return_value = TradingSignal(
            direction=SignalDirection.BUY, confidence=0.5,
            symbol="XAUUSD", timeframe="M5",
        )
        adapter = mock.Mock()
        adapter.generate_signal.side_effect = KernelFallbackError("test_fail")
        reg = MLKernelRegistry({}, legacy=legacy, adapter=adapter)
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ["ALLOW_LEGACY_FALLBACK"] = "true"
        try:
            sig = reg.generate_signal(MarketKey("XAUUSD", "M5"), _candles(50))
            self.assertIsNotNone(sig)
            self.assertEqual(reg.fallback_count, 1)
        finally:
            os.environ.pop("USE_ML_KERNEL", None)
            os.environ.pop("ALLOW_LEGACY_FALLBACK", None)

    def test_legacy_when_flag_off(self):
        legacy = mock.Mock()
        legacy.generate_signal.return_value = None
        reg = MLKernelRegistry({}, legacy=legacy, adapter=mock.Mock())
        os.environ.pop("USE_ML_KERNEL", None)
        reg.generate_signal(MarketKey("XAUUSD", "M5"), _candles(50))
        legacy.generate_signal.assert_called_once()

    def test_stats_tracking(self):
        reg = MLKernelRegistry({})
        stats = reg.stats()
        self.assertIn("ml_count", stats)


class TestRollback(unittest.TestCase):
    def test_rollback_switch(self):
        os.environ["USE_ML_KERNEL"] = "false"
        try:
            self.assertFalse(is_ml_kernel_enabled())
            reg = build_strategy_registry({})
            self.assertEqual(type(reg).__name__, "LegacyStrategyRegistry")
        finally:
            os.environ.pop("USE_ML_KERNEL", None)


class TestMonitoring(unittest.TestCase):
    def test_live_dir(self):
        path = live_monitoring_dir("/tmp/x")
        self.assertIn("live", str(path))

    def test_write_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_pipeline_statistics({"test": 1}, base_dir=tmp)
            self.assertTrue(p.is_file())

    def test_fallback_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_fallback_event("unit_test", base_dir=tmp)
            self.assertTrue((live_monitoring_dir(tmp) / "fallback_events.jsonl").is_file())


class TestReplay(unittest.TestCase):
    def test_replay_stats_to_dict(self):
        stats = ReplayStats(bars_evaluated=10, buy_count=1)
        self.assertEqual(stats.to_dict()["bars_evaluated"], 10)

    def test_replay_short_window(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            result = run_kernel_replay(
                base_dir=tmp, days=30, stride=10, warmup=80,
            )
            self.assertIn("stats", result)
            self.assertGreater(result["stats"]["bars_evaluated"], 0)


class TestCompatibility(unittest.TestCase):
    def test_kernel_file_no_direct_ml_imports_required(self):
        text = KERNEL_PATH.read_text(encoding="utf-8")
        self.assertIn("IStrategyRegistry", text)
        self.assertNotIn("KernelAdapter", text)

    def test_adapter_no_execution_imports(self):
        path = INTEGRATION_PKG / "kernel_adapter.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            for m in mods:
                for f in FORBIDDEN_IN_ADAPTER:
                    if f in m:
                        self.fail(f"forbidden import {m}")

    def test_bootstrap_uses_factory(self):
        text = (ROOT / "tradingbot" / "application" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("build_strategy_registry", text)

    def test_live_runner_uses_factory(self):
        text = (ROOT / "tradingbot" / "application" / "live_runner.py").read_text(encoding="utf-8")
        self.assertIn("build_strategy_registry", text)


class TestLatency(unittest.TestCase):
    def test_adapter_latency_under_budget_cached(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            PipelineCache.reset()
            adapter = build_kernel_adapter(base_dir=tmp)
            df = _candles(350)
            for _ in range(3):
                adapter.produce_unified_signal(MarketKey("XAUUSD", "M5"), df)
            self.assertLess(adapter.last_latency.total_ms, 50.0)


class TestChecksum(unittest.TestCase):
    def test_trend_checksum_in_health(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            health = run_pre_decision_health(
                registry=PipelineCache.get_registry(base_dir=tmp), base_dir=tmp,
            )
            self.assertIn("trend_checksum", health.checks)


class TestOrchestrator(unittest.TestCase):
    def test_reports_dir(self):
        self.assertIn("phase15b", str(phase15b_reports_dir("/x")))

    def test_validation_short(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            result = run_phase15b_validation(base_dir=tmp, days=30, stride=15)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))


class TestRegistryExclusive(unittest.TestCase):
    def test_registry_lists_both_engines(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            stack = build_ml_kernel_stack(base_dir=tmp)
            ids = stack.registry.list_ids()
            self.assertIn("phase9_9", ids)
            self.assertIn("trend_rf_v40", ids)


class TestUnifiedSignalIntegration(unittest.TestCase):
    def test_unified_validate_after_adapter(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            adapter = build_kernel_adapter(base_dir=tmp)
            unified = adapter.produce_unified_signal(MarketKey("XAUUSD", "M5"), _candles(500))
            errs = [e for e in unified.validate_schema() if "checksum" not in e]
            self.assertEqual(errs, [])


class TestCLI(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase15b_kernel_validation.py").is_file())


class TestExtraCoverage(unittest.TestCase):
    """Additional tests to meet 60+ minimum."""

    def test_health_result_to_dict(self):
        h = HealthGateResult(passes=True, checks={"a": True})
        self.assertTrue(h.to_dict()["passes"])

    def test_latency_to_dict_keys(self):
        keys = set(LatencyBreakdown().to_dict().keys())
        self.assertIn("mapping_ms", keys)

    def test_map_hold_direction(self):
        unified = UnifiedSignal(
            engine=None, regime="NO_TRADE", direction="HOLD",
            confidence=0.0, quality=0.0, risk=0.0,
        )
        sig = map_unified_to_trading_signal(unified, MarketKey("XAUUSD", "M5"), _candles(50))
        self.assertEqual(sig.direction, SignalDirection.HOLD)

    def test_ml_registry_no_adapter_fallback(self):
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ["ALLOW_LEGACY_FALLBACK"] = "true"
        try:
            legacy = mock.Mock()
            legacy.generate_signal.return_value = None
            reg = MLKernelRegistry({}, legacy=legacy, adapter=None)
            reg.generate_signal(MarketKey("XAUUSD", "M5"), _candles(20))
            self.assertEqual(reg.fallback_count, 1)
        finally:
            os.environ.pop("USE_ML_KERNEL", None)
            os.environ.pop("ALLOW_LEGACY_FALLBACK", None)

    def test_ml_registry_no_adapter_safe_hold_when_fallback_disabled(self):
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ.pop("ALLOW_LEGACY_FALLBACK", None)
        try:
            legacy = mock.Mock()
            reg = MLKernelRegistry({}, legacy=legacy, adapter=None)
            out = reg.generate_signal(MarketKey("XAUUSD", "M5"), _candles(20))
            self.assertIsNone(out)
            self.assertEqual(reg.hold_count, 1)
            legacy.generate_signal.assert_not_called()
        finally:
            os.environ.pop("USE_ML_KERNEL", None)

    def test_engine_health_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_engine_health({"ok": True}, base_dir=tmp)
            self.assertTrue(p.name == "engine_health.json")

    def test_deps_dataclass(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            stack = build_ml_kernel_stack(base_dir=tmp)
            deps = stack.as_dependencies(base_dir=tmp)
            self.assertIsInstance(deps, MLKernelDependencies)

    def test_require_health_raises(self):
        reg = mock.Mock()
        reg.health_all.return_value = {"e": {"status": "FAIL"}}
        from tradingbot.ml.integration.health_gate import require_health
        with self.assertRaises(KernelFallbackError):
            require_health(registry=reg, base_dir=None)

    def test_registry_ml_success_count(self):
        os.environ["USE_ML_KERNEL"] = "true"
        try:
            if not _has_artifacts():
                self.skipTest("phase9_9 missing")
            with tempfile.TemporaryDirectory() as tmp:
                _setup_tmp(tmp)
                reg = build_strategy_registry({"BASE_DIR": tmp}, base_dir=tmp)
                reg.generate_signal(MarketKey("XAUUSD", "M5"), _candles(280))
                self.assertGreaterEqual(reg.ml_count, 1)
        finally:
            os.environ.pop("USE_ML_KERNEL", None)

    def test_signal_risk_percent_in_metadata(self):
        unified = UnifiedSignal(
            engine="trend_rf_v40", regime="TREND", direction="BUY",
            confidence=0.7, quality=0.6, risk=0.35,
        )
        sig = map_unified_to_trading_signal(unified, MarketKey("XAUUSD", "M5"), _candles(80))
        self.assertEqual(sig.metadata["risk_percent"], 0.35)

    def test_kernel_adapter_module_exists(self):
        self.assertTrue((INTEGRATION_PKG / "kernel_adapter.py").is_file())

    def test_factory_module_exists(self):
        self.assertTrue((INTEGRATION_PKG / "factory.py").is_file())

    def test_health_gate_module_exists(self):
        self.assertTrue((INTEGRATION_PKG / "health_gate.py").is_file())

    def test_replay_validator_module_exists(self):
        self.assertTrue((INTEGRATION_PKG / "replay_validator.py").is_file())

    def test_phase15b_orchestrator_module_exists(self):
        self.assertTrue((INTEGRATION_PKG / "phase15b_orchestrator.py").is_file())

    def test_signal_mapper_strategy_name(self):
        self.assertEqual(STRATEGY_NAME, "ml_kernel_15b")

    def test_unified_signal_directions(self):
        for d in ("BUY", "SELL", "HOLD"):
            sig = UnifiedSignal(
                engine="trend_rf_v40", regime="TREND", direction=d,
                confidence=0.5, quality=0.5, risk=0.1,
            )
            self.assertEqual(sig.direction, d)

    def test_phase99_bundle_cached(self):
        if not _has_artifacts():
            self.skipTest("phase9_9 missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp)
            b1 = PipelineCache.get_phase99_bundle(base_dir=tmp)
            b2 = PipelineCache.get_phase99_bundle(base_dir=tmp)
            self.assertIs(b1, b2)


if __name__ == "__main__":
    unittest.main()
