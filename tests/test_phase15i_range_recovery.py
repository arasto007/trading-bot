"""Phase 15I — range engine recovery tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine, compute_regime_strength
from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID, TREND_MODEL_ID
from tradingbot.ml.decision_engine.decision_types import EngineSignal, MarketContext
from tradingbot.ml.research.phase15i.config import (
    MIN_RANGE_CONTRIBUTION,
    REGIME_PARITY_TARGET,
    TREND_STABILITY_TOLERANCE,
)
from tradingbot.ml.research.phase15i.recovery_adapter import (
    RangeAwareConfidenceEngine,
    RangeRecoveryOrchestrator,
    build_range_recovery_orchestrator,
)
from tradingbot.ml.research.phase15i.report_generator import write_phase15i_reports
from tradingbot.ml.research.phase15i.validator import validate_phase15i

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase15i"


def _range_ctx(*, signal: str = "SELL", prob: float = 0.40, conf: float = 0.20) -> MarketContext:
    return MarketContext(
        symbol="XAUUSD",
        timeframe="M5",
        regime="RANGE",
        session="london",
        volatility=25.0,
        regime_strength=0.45,
        features={"adx": 15.0, "atr_percentile": 20.0, "spread_pips": 2.0},
        range_signal=EngineSignal(signal=signal, confidence=conf, model=RANGE_MODEL_ID, probability=prob),
        trend_signal=EngineSignal(signal="HOLD", confidence=0.0, model=TREND_MODEL_ID, probability=0.5),
    )


def _trend_ctx(*, signal: str = "BUY", conf: float = 0.70) -> MarketContext:
    return MarketContext(
        symbol="XAUUSD",
        timeframe="M5",
        regime="TREND",
        session="london",
        volatility=40.0,
        regime_strength=0.80,
        features={"adx": 30.0, "atr_percentile": 50.0, "spread_pips": 2.0},
        range_signal=EngineSignal(signal="HOLD", confidence=0.0, model=RANGE_MODEL_ID, probability=0.5),
        trend_signal=EngineSignal(signal=signal, confidence=conf, model=TREND_MODEL_ID, probability=0.65),
    )


class TestConfig(unittest.TestCase):
    def test_regime_target(self):
        self.assertLess(REGIME_PARITY_TARGET, 0.02)

    def test_trend_tolerance(self):
        self.assertEqual(TREND_STABILITY_TOLERANCE, 0.05)

    def test_min_range_contribution(self):
        self.assertGreater(MIN_RANGE_CONTRIBUTION, 0.0)


class TestRangeAwareConfidence(unittest.TestCase):
    def test_range_sell_uses_directional_probability(self):
        eng = RangeAwareConfidenceEngine()
        ctx = _range_ctx(signal="SELL", prob=0.40, conf=0.20)
        v = eng.from_context(ctx, 0.20)
        self.assertGreaterEqual(v, 0.55)

    def test_range_buy_uses_probability(self):
        eng = RangeAwareConfidenceEngine()
        ctx = _range_ctx(signal="BUY", prob=0.60, conf=0.20)
        v = eng.from_context(ctx, 0.20)
        self.assertGreaterEqual(v, 0.60)

    def test_trend_unchanged_compression(self):
        # Phase 22D: TREND uses the same directional-probability recovery as RANGE.
        eng = RangeAwareConfidenceEngine()
        base = ConfidenceEngine()
        ctx = _trend_ctx(conf=0.70)
        recovered = eng.from_context(ctx, 0.70)
        compressed = base.from_context(ctx, 0.70)
        self.assertGreater(recovered, compressed)
        self.assertAlmostEqual(recovered, 0.70, places=4)

    def test_range_hold_no_boost(self):
        eng = RangeAwareConfidenceEngine()
        ctx = _range_ctx(signal="HOLD", prob=0.5, conf=0.0)
        base = ConfidenceEngine()
        self.assertEqual(eng.from_context(ctx, 0.0), base.from_context(ctx, 0.0))

    def test_monotonic_higher_prob(self):
        eng = RangeAwareConfidenceEngine()
        low = eng.from_context(_range_ctx(signal="BUY", prob=0.56, conf=0.12), 0.12)
        high = eng.from_context(_range_ctx(signal="BUY", prob=0.80, conf=0.60), 0.60)
        self.assertLess(low, high)


class TestRangeRecoveryOrchestrator(unittest.TestCase):
    def test_build_orchestrator(self):
        o = build_range_recovery_orchestrator()
        self.assertIsInstance(o, RangeRecoveryOrchestrator)

    def test_range_decision_passes_policy(self):
        o = build_range_recovery_orchestrator()
        d = o.decide(_range_ctx(signal="SELL", prob=0.35, conf=0.30))
        self.assertIn(d.action, ("BUY", "SELL", "HOLD"))

    def test_delegates_policy(self):
        o = build_range_recovery_orchestrator()
        self.assertEqual(o.policy.min_confidence, 0.55)

    def test_trend_decision_unchanged_engine(self):
        from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

        o = build_range_recovery_orchestrator()
        d = o.decide(_trend_ctx())
        self.assertEqual(d.engine, resolve_active_trend_engine_id())


class TestRegimeStrength(unittest.TestCase):
    def test_range_strength_below_one(self):
        s = compute_regime_strength({"adx": 15.0, "atr_percentile": 20.0}, "RANGE")
        self.assertLess(s, 1.0)

    def test_trend_strength(self):
        s = compute_regime_strength({"adx": 30.0, "ema50_slope": 0.2}, "TREND")
        self.assertGreater(s, 0.0)


class TestValidator(unittest.TestCase):
    def _base(self, **overrides):
        d = {
            "range_pipeline": {"diagnosis": "confidence_engine_compression_at_decision_14_1"},
            "router_balance": {"router_calls_phase9_9_correctly": True},
            "regime_distribution": {"within_1pct": True},
            "recovery_replay": {"primary_days": 180, "windows": {"180d": {
                "range_trades": 50, "trend_trades": 100, "range_contribution_pct": 0.33,
            }}},
            "baseline_replay": {"windows": {"180d": {"range_trades": 10, "trend_trades": 100}}},
            "range_safety": {"checksum_unchanged": True, "bundle_touched": False},
            "trend_safety": {"checksum_unchanged": True, "bundle_touched": False},
            "recovery_justified": True,
        }
        d.update(overrides)
        return validate_phase15i(**d)

    def test_pass_case(self):
        v = self._base()
        self.assertTrue(v["all_passed"])

    def test_fail_no_range(self):
        v = self._base(recovery_replay={"primary_days": 180, "windows": {"180d": {
            "range_trades": 0, "trend_trades": 100,
        }}})
        self.assertFalse(v["checks"]["range_contributes_trades"])

    def test_fail_checksum(self):
        v = self._base(range_safety={"checksum_unchanged": False, "bundle_touched": False})
        self.assertFalse(v["all_passed"])

    def test_trend_stable(self):
        v = self._base()
        self.assertTrue(v["checks"]["trend_performance_stable"])


class TestReportGenerator(unittest.TestCase):
    def test_writes_nine_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15i_reports(
                range_pipeline={"phase": "15I"},
                phase99_audit={"phase": "15I"},
                router_balance={"phase": "15I"},
                risk_blocks={"phase": "15I"},
                quality_blocks={"phase": "15I"},
                feature_validation={"phase": "15I"},
                range_recovery={"phase": "15I"},
                regime_distribution={"phase": "15I"},
                final_report={"phase": "15I", "status": "PASS"},
                base_dir=tmp,
            )
            files = list(out.glob("*.json"))
            self.assertEqual(len(files), 9)


class TestModuleImports(unittest.TestCase):
    def test_range_path_audit(self):
        from tradingbot.ml.research.phase15i.range_path_audit import audit_range_pipeline
        self.assertTrue(callable(audit_range_pipeline))

    def test_router_balance(self):
        from tradingbot.ml.research.phase15i.router_balance import audit_router_balance
        self.assertTrue(callable(audit_router_balance))

    def test_regime_distribution(self):
        from tradingbot.ml.research.phase15i.regime_distribution import measure_regime_distribution
        self.assertTrue(callable(measure_regime_distribution))

    def test_phase99_audit(self):
        from tradingbot.ml.research.phase15i.phase99_signal_audit import audit_phase99_signals
        self.assertTrue(callable(audit_phase99_signals))

    def test_feature_validation(self):
        from tradingbot.ml.research.phase15i.range_feature_validation import validate_range_features
        self.assertTrue(callable(validate_range_features))

    def test_router_validation(self):
        from tradingbot.ml.research.phase15i.range_router_validation import validate_range_router
        self.assertTrue(callable(validate_range_router))

    def test_risk_audit(self):
        from tradingbot.ml.research.phase15i.risk_filter_audit import audit_risk_blocks
        self.assertTrue(callable(audit_risk_blocks))

    def test_quality_audit(self):
        from tradingbot.ml.research.phase15i.quality_filter_audit import audit_quality_blocks
        self.assertTrue(callable(audit_quality_blocks))

    def test_signal_flow(self):
        from tradingbot.ml.research.phase15i.signal_flow import trace_range_pipeline
        self.assertTrue(callable(trace_range_pipeline))

    def test_replay(self):
        from tradingbot.ml.research.phase15i.replay import replay_with_contribution
        self.assertTrue(callable(replay_with_contribution))

    def test_orchestrator(self):
        from tradingbot.ml.research.phase15i.orchestrator import run_phase15i_recovery
        self.assertTrue(callable(run_phase15i_recovery))


class TestRangePathDiagnosis(unittest.TestCase):
    def test_diagnose_compression(self):
        from tradingbot.ml.research.phase15i.range_path_audit import _diagnose
        d = _diagnose({"decision_14_1": 5}, {"range_actionable_kernel": 0})
        self.assertEqual(d, "confidence_engine_compression_at_decision_14_1")

    def test_diagnose_open(self):
        from tradingbot.ml.research.phase15i.range_path_audit import _diagnose
        d = _diagnose({}, {"range_actionable_kernel": 3})
        self.assertEqual(d, "range_path_partially_open")

    def test_diagnose_engine_hold(self):
        from tradingbot.ml.research.phase15i.range_path_audit import _diagnose
        d = _diagnose({"phase9_9": 2}, {"range_actionable_kernel": 0})
        self.assertEqual(d, "phase9_9_engine_hold_dominant")


class TestSignalFlowRecord(unittest.TestCase):
    def test_to_dict_keys(self):
        from tradingbot.ml.research.phase15i.signal_flow import RangeFlowRecord
        r = RangeFlowRecord(
            timestamp="t", regime="RANGE", engine_selected="phase9_9",
            range_signal="SELL", range_probability=0.4, range_confidence=0.2,
            trend_signal="HOLD", decision_action="HOLD", decision_confidence=0.1,
            calibrated_action="HOLD", calibrated_confidence=0.1, mapped_confidence=None,
            risk_allowed=False, risk_blocked_by=None, quality_allowed=False,
            quality_blocked_by=None, kernel_action="HOLD",
        )
        d = r.to_dict()
        self.assertIn("drop_stage", d)
        self.assertIn("range_probability", d)


class TestRegimeDistribution(unittest.TestCase):
    def test_distribution_sums(self):
        from tradingbot.ml.research.phase15i.regime_distribution import _distribution
        df = pd.DataFrame({
            "adx": [10, 30, 10, 30],
            "atr_percentile": [20, 50, 20, 50],
            "ema50_slope": [0.1, 0.2, 0.1, 0.2],
            "spread_pips": [2, 2, 2, 2],
            "volatility": [1, 2, 1, 2],
        })
        dist = _distribution(df, stride=1)
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=3)


class TestFactoryWiring(unittest.TestCase):
    def test_factory_accepts_recovery_flag(self):
        import inspect
        from tradingbot.ml.integration.factory import build_ml_kernel_stack
        sig = inspect.signature(build_ml_kernel_stack)
        self.assertIn("use_range_recovery", sig.parameters)


class TestPackageLayout(unittest.TestCase):
    def test_modules_exist(self):
        expected = [
            "range_path_audit.py", "router_balance.py", "regime_distribution.py",
            "phase99_signal_audit.py", "range_feature_validation.py",
            "range_router_validation.py", "quality_filter_audit.py",
            "risk_filter_audit.py", "signal_flow.py", "recovery_adapter.py",
            "orchestrator.py", "report_generator.py", "validator.py", "config.py",
        ]
        for name in expected:
            self.assertTrue((PKG / name).is_file(), name)

    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase15i_range_recovery.py").is_file())


class TestOrchestratorMocked(unittest.TestCase):
    def test_run_mocked(self):
        from tradingbot.ml.research.phase15i.orchestrator import run_phase15i_recovery
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tradingbot.ml.research.phase15i.orchestrator.CandleStore") as cs:
                cs.return_value.load.return_value = pd.DataFrame(
                    {"close": [1.0]}, index=pd.DatetimeIndex(["2025-01-01"], tz="UTC"),
                )
                with mock.patch("tradingbot.ml.research.phase15i.orchestrator.DatasetStore") as ds:
                    ds.return_value.load_v2.return_value = pd.DataFrame(
                        {"timestamp": ["2025-01-01"], "f": [1.0]},
                    )
                    with mock.patch(
                        "tradingbot.ml.research.phase15i.orchestrator.audit_range_pipeline",
                        return_value={"diagnosis": "confidence_engine_compression_at_decision_14_1",
                                      "drop_summary": {"decision_14_1": 1}},
                    ):
                        with mock.patch(
                            "tradingbot.ml.research.phase15i.orchestrator.measure_regime_distribution",
                            return_value={"within_1pct": True},
                        ):
                            with mock.patch(
                                "tradingbot.ml.research.phase15i.orchestrator.audit_phase99_signals",
                                return_value={"actionable_count": 10},
                            ):
                                with mock.patch(
                                    "tradingbot.ml.research.phase15i.orchestrator.audit_router_balance",
                                    return_value={"router_calls_phase9_9_correctly": True},
                                ):
                                    with mock.patch(
                                        "tradingbot.ml.research.phase15i.orchestrator.audit_risk_blocks",
                                        return_value={},
                                    ):
                                        with mock.patch(
                                            "tradingbot.ml.research.phase15i.orchestrator.audit_quality_blocks",
                                            return_value={},
                                        ):
                                            with mock.patch(
                                                "tradingbot.ml.research.phase15i.orchestrator.validate_range_features",
                                                return_value={"no_missing_columns": True},
                                            ):
                                                with mock.patch(
                                                    "tradingbot.ml.research.phase15i.orchestrator.validate_range_router",
                                                    return_value={"routing_correct": True},
                                                ):
                                                    with mock.patch(
                                                        "tradingbot.ml.research.phase15i.orchestrator.replay_with_contribution",
                                                        side_effect=[
                                                            {"primary_days": 180, "windows": {"180d": {
                                                                "range_trades": 5, "trend_trades": 95,
                                                            }}},
                                                            {"primary_days": 180, "windows": {"180d": {
                                                                "range_trades": 40, "trend_trades": 95,
                                                                "range_contribution_pct": 0.30,
                                                            }}},
                                                        ],
                                                    ):
                                                        with mock.patch(
                                                            "tradingbot.ml.research.phase15i.orchestrator.audit_range_safety",
                                                            return_value={"checksum_unchanged": True, "bundle_touched": False},
                                                        ):
                                                            with mock.patch(
                                                                "tradingbot.ml.research.phase15i.orchestrator.audit_trend_safety",
                                                                return_value={"checksum_unchanged": True, "bundle_touched": False},
                                                            ):
                                                                r = run_phase15i_recovery(base_dir=tmp, days=30)
        self.assertEqual(r.recommendation, "READY_FOR_PHASE15J")


class TestRecoveryJustified(unittest.TestCase):
    def test_justified_when_compression(self):
        from tradingbot.ml.research.phase15i.orchestrator import _recovery_justified
        self.assertTrue(_recovery_justified(
            {"diagnosis": "x", "drop_summary": {"decision_14_1": 1}},
            {"actionable_count": 5},
        ))

    def test_not_justified_no_signals(self):
        from tradingbot.ml.research.phase15i.orchestrator import _recovery_justified
        self.assertFalse(_recovery_justified({"drop_summary": {}}, {"actionable_count": 0}))


class TestStrategySelector(unittest.TestCase):
    def test_range_engine_id(self):
        from tradingbot.ml.decision_engine.strategy_selector import select_engine
        self.assertEqual(select_engine("RANGE"), RANGE_MODEL_ID)

    def test_trend_engine_id(self):
        from tradingbot.ml.decision_engine.strategy_selector import select_engine
        from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
        self.assertEqual(select_engine("TREND"), resolve_active_trend_engine_id())

    def test_blocked_high_vol(self):
        from tradingbot.ml.decision_engine.strategy_selector import select_engine
        self.assertIsNone(select_engine("HIGH_VOLATILITY"))


class TestPhase99FeatureMap(unittest.TestCase):
    def test_map_keys(self):
        from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP
        self.assertIn("ema50_slope", PHASE99_FEATURE_MAP)

    def test_row_mapping(self):
        from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
        row = pd.Series({"phase99_ema50_slope": 0.1, "phase99_candle_direction": 1.0})
        out = row_for_phase99_range(row)
        self.assertIn("ema50_slope", out.index)


class TestReplayStructure(unittest.TestCase):
    def test_primary_days_default(self):
        from tradingbot.ml.research.phase15i.replay import replay_with_contribution
        with mock.patch("tradingbot.ml.integration.factory.build_ml_kernel_stack") as bs:
            with mock.patch("tradingbot.ml.integration.factory.build_kernel_adapter") as ba:
                stack = mock.MagicMock()
                bs.return_value = stack
                adapter = mock.MagicMock()
                adapter.last_unified_signal = None
                ba.return_value = adapter
                candles = pd.DataFrame(
                    {"close": [1.0] * 400},
                    index=pd.date_range("2025-01-01", periods=400, freq="5min", tz="UTC"),
                )
                out = replay_with_contribution(candles, days_list=(30,), stride=50, warmup=10)
        self.assertEqual(out["primary_days"], 30)


class TestReportsDir(unittest.TestCase):
    def test_reports_path(self):
        from tradingbot.ml.research.phase15i.config import reports_dir
        self.assertTrue(str(reports_dir()).endswith("phase15i"))


class TestSyntax(unittest.TestCase):
    def test_pkg_syntax(self):
        for py in PKG.glob("*.py"):
            ast.parse(py.read_text(encoding="utf-8"))


class TestConfidenceComparison(unittest.TestCase):
    def test_compression_reduces_range(self):
        base = ConfidenceEngine()
        ctx = _range_ctx(signal="SELL", prob=0.40, conf=0.20)
        compressed = base.from_context(ctx, 0.20)
        recovered = RangeAwareConfidenceEngine().from_context(ctx, 0.20)
        self.assertGreater(recovered, compressed)


class TestValidatorFields(unittest.TestCase):
    def test_output_keys(self):
        v = validate_phase15i(
            range_pipeline={"diagnosis": "x"},
            router_balance={"router_calls_phase9_9_correctly": True},
            regime_distribution={"within_1pct": True},
            recovery_replay={"primary_days": 180, "windows": {"180d": {"range_trades": 20, "trend_trades": 80}}},
            baseline_replay={"windows": {"180d": {"range_trades": 5, "trend_trades": 80}}},
            range_safety={"checksum_unchanged": True, "bundle_touched": False},
            trend_safety={"checksum_unchanged": True, "bundle_touched": False},
            recovery_justified=True,
        )
        self.assertIn("range_contribution_pct", v)
        self.assertIn("failed", v)


class TestRangeSellThreshold(unittest.TestCase):
    def test_sell_at_045(self):
        eng = RangeAwareConfidenceEngine()
        ctx = _range_ctx(signal="SELL", prob=0.45, conf=0.10)
        self.assertGreaterEqual(eng.from_context(ctx, 0.10), 0.55)

    def test_sell_below_threshold(self):
        eng = RangeAwareConfidenceEngine()
        ctx = _range_ctx(signal="SELL", prob=0.50, conf=0.0)
        self.assertLess(eng.from_context(ctx, 0.0), 0.55)


class TestRangeBuyThreshold(unittest.TestCase):
    def test_buy_at_055(self):
        eng = RangeAwareConfidenceEngine()
        ctx = _range_ctx(signal="BUY", prob=0.55, conf=0.10)
        self.assertGreaterEqual(eng.from_context(ctx, 0.10), 0.55)

    def test_buy_strong(self):
        eng = RangeAwareConfidenceEngine()
        ctx = _range_ctx(signal="BUY", prob=0.90, conf=0.80)
        self.assertGreaterEqual(eng.from_context(ctx, 0.80), 0.85)


class TestDiagnoseRouter(unittest.TestCase):
    def test_router_block(self):
        from tradingbot.ml.research.phase15i.range_path_audit import _diagnose
        self.assertEqual(_diagnose({"router": 1}, {}), "router_not_selecting_phase9_9")

    def test_risk_block(self):
        from tradingbot.ml.research.phase15i.range_path_audit import _diagnose
        self.assertEqual(_diagnose({"risk_14_2b": 1}, {}), "risk_gate_blocking_range")

    def test_quality_block(self):
        from tradingbot.ml.research.phase15i.range_path_audit import _diagnose
        self.assertEqual(_diagnose({"quality_14_3": 1}, {}), "quality_gate_blocking_range")


class TestRangeRecoveryWrapper(unittest.TestCase):
    def test_has_decide(self):
        o = RangeRecoveryOrchestrator()
        self.assertTrue(hasattr(o, "decide"))

    def test_inner_orchestrator(self):
        o = RangeRecoveryOrchestrator()
        self.assertIsNotNone(o.inner)


class TestBlockedRegimes(unittest.TestCase):
    def test_no_trade(self):
        from tradingbot.ml.decision_engine.strategy_selector import select_engine
        self.assertIsNone(select_engine("NO_TRADE"))

    def test_routing_action_range(self):
        from tradingbot.ml.decision_engine.strategy_selector import routing_action
        self.assertIn("phase9_9", routing_action("RANGE"))


class TestConfigConstants(unittest.TestCase):
    def test_default_days(self):
        from tradingbot.ml.research.phase15i.config import DEFAULT_DAYS
        self.assertEqual(DEFAULT_DAYS, 180)

    def test_engine_ids(self):
        from tradingbot.ml.research.phase15i.config import RANGE_ENGINE_ID, TREND_ENGINE_ID
        self.assertEqual(RANGE_ENGINE_ID, "phase9_9")
        self.assertEqual(TREND_ENGINE_ID, "trend_rf_v40")


class TestValidatorTrendDelta(unittest.TestCase):
    def test_trend_unstable(self):
        v = validate_phase15i(
            range_pipeline={"diagnosis": "x"},
            router_balance={"router_calls_phase9_9_correctly": True},
            regime_distribution={"within_1pct": True},
            recovery_replay={"primary_days": 180, "windows": {"180d": {"range_trades": 50, "trend_trades": 50}}},
            baseline_replay={"windows": {"180d": {"range_trades": 10, "trend_trades": 100}}},
            range_safety={"checksum_unchanged": True, "bundle_touched": False},
            trend_safety={"checksum_unchanged": True, "bundle_touched": False},
            recovery_justified=True,
        )
        self.assertFalse(v["checks"]["trend_performance_stable"])


class TestAssignDrop(unittest.TestCase):
    def test_assign_once(self):
        from tradingbot.ml.research.phase15i.signal_flow import RangeFlowRecord, _assign_drop
        r = RangeFlowRecord(
            timestamp="t", regime="RANGE", engine_selected="phase9_9",
            range_signal="HOLD", range_probability=0.5, range_confidence=0.0,
            trend_signal="HOLD", decision_action="HOLD", decision_confidence=0.0,
            calibrated_action="HOLD", calibrated_confidence=0.0, mapped_confidence=None,
            risk_allowed=False, risk_blocked_by=None, quality_allowed=False,
            quality_blocked_by=None, kernel_action="HOLD",
        )
        _assign_drop(r, "a", "reason1")
        _assign_drop(r, "b", "reason2")
        self.assertEqual(r.drop_stage, "a")


class TestReportFiles(unittest.TestCase):
    def test_final_report_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15i_reports(
                range_pipeline={}, phase99_audit={}, router_balance={},
                risk_blocks={}, quality_blocks={}, feature_validation={},
                range_recovery={}, regime_distribution={},
                final_report={"status": "PASS"}, base_dir=tmp,
            )
            self.assertTrue((out / "phase15i_final_report.json").is_file())

    def test_range_pipeline_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15i_reports(
                range_pipeline={"phase": "15I"}, phase99_audit={}, router_balance={},
                risk_blocks={}, quality_blocks={}, feature_validation={},
                range_recovery={}, regime_distribution={},
                final_report={}, base_dir=tmp,
            )
            self.assertTrue((out / "range_pipeline.json").is_file())

    def test_regime_distribution_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15i_reports(
                range_pipeline={}, phase99_audit={}, router_balance={},
                risk_blocks={}, quality_blocks={}, feature_validation={},
                range_recovery={}, regime_distribution={"within_1pct": True},
                final_report={}, base_dir=tmp,
            )
            data = json.loads((out / "regime_distribution.json").read_text(encoding="utf-8"))
            self.assertTrue(data["within_1pct"])


class TestRangeEngineId(unittest.TestCase):
    def test_policy_range_id(self):
        from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID
        self.assertEqual(RANGE_MODEL_ID, "phase9_9")


if __name__ == "__main__":
    unittest.main()
