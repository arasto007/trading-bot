"""Phase 15A — production integration preparation tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.phase15a.checklist import CHECKLIST_ITEMS, build_production_checklist, render_checklist_markdown
from tradingbot.ml.phase15a.config import (
    BUNDLE_VERSION,
    EXPECTED_DATASET_FINGERPRINT,
    RANGE_ENGINE_ID,
    TREND_ENGINE_ID,
    phase15a_reports_dir,
    trend_rf_bundle_root,
    trend_rf_checksum_path,
    trend_rf_metadata_path,
    trend_rf_model_path,
)
from tradingbot.ml.phase15a.engine_discovery import discover_engines
from tradingbot.ml.phase15a.engine_registry import EngineRegistry, Phase99EngineWrapper, TrendRfEngineWrapper
from tradingbot.ml.phase15a.health_check import run_health_checks
from tradingbot.ml.phase15a.interfaces import (
    CalibrationProvider,
    DecisionProvider,
    QualityProvider,
    RiskProvider,
    RouterProvider,
)
from tradingbot.ml.phase15a.orchestrator import run_phase15a_preparation
from tradingbot.ml.phase15a.pipeline_validator import _StubCalibration, _StubQuality, _StubRisk, validate_pipeline
from tradingbot.ml.phase15a.report_generator import (
    build_architecture_future_md,
    build_model_inventory,
    build_technical_debt_update,
)
from tradingbot.ml.phase15a.trend_bundle import (
    TrendRfBundle,
    freeze_trend_bundle_from_candles,
    load_trend_bundle,
    sha256_file,
    validate_trend_checksum,
)
from tradingbot.ml.phase15a.unified_signal import SIGNAL_SCHEMA, UnifiedSignal
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS

PHASE15A_PKG = ROOT / "tradingbot" / "ml" / "phase15a"
FORBIDDEN = ("tradingbot.kernel", "order_send", "risk_gate", "mt5_execution")


def _candles(n: int = 1500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.3, n).cumsum()
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.2, n)
    vol = rng.integers(100, 500, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=ts,
    )


def _dataset(n: int = 500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
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


def _setup_tmp(tmp: str, *, n_candles: int = 1500, copy_phase99: bool = False) -> None:
    if copy_phase99:
        import shutil
        src = ROOT / "data" / "ml" / "research" / "phase9_9_best"
        if src.is_dir():
            dst = Path(tmp) / "ml" / "research" / "phase9_9_best"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    CandleStore(tmp).store("XAUUSD", "M5", _candles(n_candles))
    DatasetStore(tmp).store_v2("XAUUSD", "M5", _dataset())


class TestPhase15AConfig(unittest.TestCase):
    def test_engine_ids(self):
        self.assertEqual(TREND_ENGINE_ID, "trend_rf_v40")
        self.assertEqual(RANGE_ENGINE_ID, "phase9_9")

    def test_bundle_version(self):
        self.assertEqual(BUNDLE_VERSION, "trend_rf_v40.1")

    def test_dataset_fingerprint(self):
        self.assertEqual(EXPECTED_DATASET_FINGERPRINT, "70b38325ee1c7e1e")

    def test_reports_dir_under_ml(self):
        path = phase15a_reports_dir("/tmp/x")
        self.assertIn("phase15a", str(path))


class TestUnifiedSignal(unittest.TestCase):
    def test_signal_creation(self):
        sig = UnifiedSignal(
            engine="trend_rf_v40", regime="TREND", direction="BUY",
            confidence=0.7, quality=0.8, risk=0.25,
        )
        self.assertTrue(sig.checksum)
        self.assertTrue(sig.timestamp)

    def test_signal_roundtrip(self):
        sig = UnifiedSignal(
            engine="phase9_9", regime="RANGE", direction="SELL",
            confidence=0.6, quality=0.5, risk=0.1, sl=1.0, tp=2.0,
        )
        restored = UnifiedSignal.from_dict(sig.to_dict())
        self.assertEqual(restored.direction, "SELL")
        self.assertEqual(restored.engine, "phase9_9")

    def test_signal_schema_required_fields(self):
        self.assertIn("engine", SIGNAL_SCHEMA["required_fields"])
        self.assertIn("checksum", SIGNAL_SCHEMA["required_fields"])

    def test_signal_valid_direction(self):
        sig = UnifiedSignal(
            engine=None, regime="NO_TRADE", direction="HOLD",
            confidence=0.0, quality=0.0, risk=0.0,
        )
        self.assertEqual(sig.validate_schema(), [])

    def test_signal_invalid_direction(self):
        sig = UnifiedSignal(
            engine=None, regime="TREND", direction="INVALID",
            confidence=0.5, quality=0.5, risk=0.1,
        )
        self.assertTrue(any("direction" in e for e in sig.validate_schema()))

    def test_signal_confidence_range(self):
        sig = UnifiedSignal(
            engine=None, regime="TREND", direction="BUY",
            confidence=1.5, quality=0.5, risk=0.1,
        )
        self.assertIn("confidence out of range", sig.validate_schema())

    def test_signal_checksum_stable(self):
        sig = UnifiedSignal(
            engine="trend_rf_v40", regime="TREND", direction="BUY",
            confidence=0.65, quality=0.7, risk=0.25,
            timestamp="2024-01-01T00:00:00+00:00",
        )
        sig.checksum = sig.compute_checksum()
        self.assertEqual(sig.validate_schema(), [])

    def test_direction_values(self):
        self.assertEqual(set(SIGNAL_SCHEMA["direction_values"]), {"BUY", "SELL", "HOLD"})


class TestInterfaces(unittest.TestCase):
    def test_decision_provider_structural(self):
        self.assertIsInstance(DecisionOrchestrator(), DecisionProvider)

    def test_calibration_stub(self):
        self.assertIsInstance(_StubCalibration(), CalibrationProvider)

    def test_risk_stub(self):
        self.assertIsInstance(_StubRisk(), RiskProvider)

    def test_quality_stub(self):
        self.assertIsInstance(_StubQuality(), QualityProvider)

    def test_router_protocol_exists(self):
        class _R:
            def route(self, context, row):
                return {"engine": "trend_rf_v40"}

        self.assertIsInstance(_R(), RouterProvider)


class TestTrendBundle(unittest.TestCase):
    def test_freeze_and_load_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _candles(1500)
            bundle = freeze_trend_bundle_from_candles(candles, base_dir=tmp)
            self.assertIsInstance(bundle, TrendRfBundle)
            self.assertTrue(trend_rf_model_path(tmp).is_file())
            self.assertTrue(trend_rf_checksum_path(tmp).is_file())
            loaded = load_trend_bundle(base_dir=tmp, build_if_missing=False)
            self.assertEqual(len(loaded.feature_order), len(bundle.feature_order))

    def test_validate_checksum_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            chk = validate_trend_checksum(base_dir=tmp)
            self.assertTrue(chk["valid"])

    def test_validate_checksum_fail_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            trend_rf_model_path(tmp).write_bytes(b"tampered")
            chk = validate_trend_checksum(base_dir=tmp)
            self.assertFalse(chk["valid"])

    def test_metadata_has_training_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            meta = json.loads(trend_rf_metadata_path(tmp).read_text(encoding="utf-8"))
            self.assertIn("training_fingerprint", meta)
            self.assertEqual(meta["version"], BUNDLE_VERSION)

    def test_feature_order_matches_trend_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            self.assertEqual(set(bundle.feature_order), set(TREND_ML_FEATURE_COLUMNS))

    def test_load_missing_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_trend_bundle(base_dir=tmp, build_if_missing=False)

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.bin"
            p.write_bytes(b"abc")
            self.assertEqual(len(sha256_file(p)), 64)

    def test_bundle_root_path(self):
        path = trend_rf_bundle_root("/data")
        self.assertTrue(str(path).endswith("trend_rf_bundle"))

    def test_predict_proba_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            row = {c: 0.0 for c in bundle.feature_order}
            proba = bundle.predict_proba(row)
            self.assertGreaterEqual(proba, 0.0)
            self.assertLessEqual(proba, 1.0)

    def test_checksum_missing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            chk = validate_trend_checksum(base_dir=tmp)
            self.assertFalse(chk["valid"])
            self.assertEqual(chk["reason"], "bundle_or_checksum_missing")


class TestEngineRegistry(unittest.TestCase):
    def test_registry_register_get(self):
        reg = EngineRegistry()
        wrapper = mock.Mock()
        wrapper.version.return_value = "v1"
        reg.register("test_engine", wrapper)
        self.assertEqual(reg.get("test_engine"), wrapper)
        self.assertIn("test_engine", reg.list_ids())

    def test_build_default_with_tmp(self):
        p99 = ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl"
        if not p99.is_file():
            self.skipTest("phase9_9 artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp, copy_phase99=True)
            freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            reg = EngineRegistry.build_default(base_dir=tmp, build_trend_if_missing=False)
            self.assertIn(RANGE_ENGINE_ID, reg.list_ids())
            self.assertIn(TREND_ENGINE_ID, reg.list_ids())

    def test_engine_wrapper_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
            from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
            from tradingbot.ml.decision_engine.decision_policy import TREND_ML_THRESHOLD, TREND_MODEL_ID

            inner = RecoveredTrendEngine(
                model=bundle.model, scaler=bundle.scaler, model_name="random_forest",
                threshold=TREND_ML_THRESHOLD, rule_fn=evaluate_variant_a, symbol="XAUUSD",
            )
            inner.model_version = TREND_MODEL_ID
            wrapper = TrendRfEngineWrapper(bundle, inner)
            self.assertEqual(wrapper.version(), BUNDLE_VERSION)
            self.assertIsNotNone(wrapper.checksum())

    def test_health_all(self):
        reg = EngineRegistry()
        m = mock.Mock()
        m.health.return_value = {"status": "OK"}
        reg.register("e1", m)
        self.assertIn("e1", reg.health_all())

    def test_phase99_wrapper_type(self):
        self.assertTrue(hasattr(Phase99EngineWrapper, "predict"))


class TestHealthAndDiscovery(unittest.TestCase):
    def test_discover_engines_structure(self):
        disc = discover_engines(persist_manifests=False)
        self.assertIn("active", disc)
        self.assertIn("future", disc)
        self.assertIn("deprecated", disc)

    def test_discover_future_engines(self):
        disc = discover_engines(persist_manifests=False)
        future_ids = [e["engine_id"] for e in disc["future"]]
        self.assertIn("ensemble_v1", future_ids)

    def test_discover_deprecated(self):
        disc = discover_engines(persist_manifests=False)
        dep_ids = [e["engine_id"] for e in disc["deprecated"]]
        self.assertIn("phase13_8_runtime_fit", dep_ids)

    def test_health_checks_with_frozen_trend(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp, copy_phase99=True)
            freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            health = run_health_checks(base_dir=tmp)
            self.assertIn("trend_rf_v40", health)
            self.assertIn("phase9_9", health)

    def test_checklist_items_count(self):
        self.assertGreaterEqual(len(CHECKLIST_ITEMS), 10)

    def test_checklist_markdown_render(self):
        cl = build_production_checklist(
            health={"passes": True, "phase9_9": {"passes": True}, "registry": {}},
            discovery={"active": []},
            pipeline={"passes": True, "signal_schema": SIGNAL_SCHEMA, "interfaces": {"passes": True}},
            interfaces_ok=True,
        )
        md = render_checklist_markdown(cl)
        self.assertIn("Phase 15A", md)


class TestPipelineAndReports(unittest.TestCase):
    def test_model_inventory(self):
        inv = build_model_inventory([RANGE_ENGINE_ID, TREND_ENGINE_ID], {"active": [], "inactive": []})
        self.assertEqual(len(inv["engines"]), 2)

    def test_technical_debt_update_resolves_trend(self):
        debt = build_technical_debt_update(trend_frozen=True)
        resolved_ids = [r.get("id") for r in debt["resolved"]]
        self.assertIn("TD-003", resolved_ids)

    def test_architecture_md_content(self):
        md = build_architecture_future_md()
        self.assertIn("TradingKernel", md)
        self.assertIn("UnifiedSignal", md)

    def test_pipeline_routing_only(self):
        from tradingbot.ml.decision_engine.validation import validate_routing
        routing = validate_routing()
        self.assertIn("passes", routing)

    def test_pipeline_with_data(self):
        p99 = ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl"
        if not p99.is_file():
            self.skipTest("phase9_9 artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp, copy_phase99=True, n_candles=800)
            freeze_trend_bundle_from_candles(_candles(1500), base_dir=tmp)
            reg = EngineRegistry.build_default(base_dir=tmp, build_trend_if_missing=False)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            result = validate_pipeline(candles, dataset, registry=reg, sample_bars=3)
            self.assertIn("sample_signals", result)


class TestOrchestratorAndSafety(unittest.TestCase):
    def test_orchestrator_tmp_run(self):
        p99 = ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl"
        if not p99.is_file():
            self.skipTest("phase9_9 artifacts missing")
        with tempfile.TemporaryDirectory() as tmp:
            _setup_tmp(tmp, copy_phase99=True)
            result = run_phase15a_preparation(base_dir=tmp, sample_bars=2)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertTrue(Path(result.reports_dir).is_dir())

    def test_forbidden_imports_scan(self):
        violations: list[str] = []
        for py in PHASE15A_PKG.glob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                else:
                    continue
                for module in mods:
                    for prefix in FORBIDDEN:
                        if prefix in module:
                            violations.append(f"{py.name}: {module}")
        self.assertEqual(violations, [])

    def test_cli_script_exists(self):
        cli = ROOT / "scripts" / "run_phase15a_preparation.py"
        self.assertTrue(cli.is_file())


if __name__ == "__main__":
    unittest.main()
