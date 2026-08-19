"""Phase 15H — confidence scale mapping tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.confidence_mapping.confidence_mapper import ConfidenceMapper
from tradingbot.ml.confidence_mapping.config import PARITY_TARGET, RISK_GATE_THRESHOLD
from tradingbot.ml.confidence_mapping.mapping_types import MappingAnchor, MappingCurve
from tradingbot.ml.confidence_mapping.mapping_validator import validate_mapping_curve
from tradingbot.ml.confidence_mapping.production_adapter import (
    MappedProductionRiskAdapter,
    _with_mapped_confidence,
)
from tradingbot.ml.confidence_mapping.report_generator import write_phase15h_reports
from tradingbot.ml.confidence_mapping.validator import validate_phase15h
from tradingbot.ml.risk_intelligence.risk_policy import MIN_CONFIDENCE_FOR_RISK

PKG = ROOT / "tradingbot" / "ml" / "confidence_mapping"


def _curve() -> MappingCurve:
    return MappingCurve(
        anchors=[
            MappingAnchor(0.0, 0.0, "origin"),
            MappingAnchor(0.25, 0.45, "mid"),
            MappingAnchor(0.50144, 0.767421, "ceiling"),
        ],
        frozen_ceiling=0.50144,
        research_ceiling=0.767421,
    )


class TestMappingMonotonicity(unittest.TestCase):
    def test_monotonic_grid(self):
        m = ConfidenceMapper(_curve())
        self.assertTrue(m.is_monotonic())

    def test_increasing(self):
        m = ConfidenceMapper(_curve())
        self.assertLess(m.map(0.1), m.map(0.4))

    def test_ceiling_maps_above_risk(self):
        m = ConfidenceMapper(_curve())
        self.assertGreaterEqual(m.map(0.50144), MIN_CONFIDENCE_FOR_RISK)


class TestBoundaryValues(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(ConfidenceMapper(_curve()).map(0.0), 0.0)

    def test_negative(self):
        self.assertEqual(ConfidenceMapper(_curve()).map(-0.1), 0.0)

    def test_frozen_49(self):
        m = ConfidenceMapper(_curve())
        v = m.map(0.49)
        self.assertGreater(v, 0.45)

    def test_frozen_50(self):
        m = ConfidenceMapper(_curve())
        self.assertGreater(m.map(0.50), m.map(0.49))


class TestMappingValidator(unittest.TestCase):
    def test_validate_passes_ceiling(self):
        m = ConfidenceMapper(_curve())
        v = validate_mapping_curve(m)
        self.assertTrue(v["monotonic"])
        self.assertTrue(v["passes_risk_gate_at_frozen_ceiling"])


class TestProductionAdapter(unittest.TestCase):
    def test_with_mapped_confidence(self):
        from tradingbot.ml.confidence_engine.validator import CalibratedDecision
        from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
        from tradingbot.ml.decision_engine.decision_types import FinalDecision
        from datetime import datetime, timezone

        raw = RawConfidence(
            raw_value=0.2, engine="trend_rf_v40", regime="TREND",
            model_probability=0.3, regime_strength=0.8, market_quality=0.7,
            session="london", volatility=50.0, volatility_state="normal",
            engine_signal="SELL",
        )
        dec = FinalDecision(
            action="SELL", engine="trend_rf_v40", confidence=0.2, regime="TREND",
            timestamp=datetime.now(timezone.utc), explanation=[], risk_hint=0.1, trace=[],
        )
        cal = CalibratedDecision(
            decision=dec, raw_confidence=raw, calibrated=mock.Mock(),
            final_action="SELL", final_confidence=0.49,
        )
        mapped = _with_mapped_confidence(cal, 0.77)
        self.assertEqual(mapped.final_confidence, 0.77)

    def test_adapter_has_evaluate(self):
        self.assertTrue(callable(MappedProductionRiskAdapter.evaluate))


class TestConfig(unittest.TestCase):
    def test_parity_target(self):
        self.assertEqual(PARITY_TARGET, 0.98)

    def test_risk_gate_matches_policy(self):
        self.assertEqual(RISK_GATE_THRESHOLD, MIN_CONFIDENCE_FOR_RISK)


class TestReportGenerator(unittest.TestCase):
    def test_writes_eight_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15h_reports(
                mapping_curve={}, mapping_validation={}, research_vs_production={},
                production_replay={}, latency_report={}, range_safety={},
                trend_safety={}, final_report={"status": "PASS"}, base_dir=tmp,
            )
            self.assertEqual(len(list(out.glob("*.json"))), 8)


class TestPhase15HValidator(unittest.TestCase):
    def test_pass_case(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 10}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.99},
            mapping_validation={"monotonic": True, "passes_risk_gate_at_frozen_ceiling": True},
            latency_report={"increase_ratio": 0.01},
            range_safety={"checksum_unchanged": True},
            trend_safety={"checksum_unchanged": True},
        )
        self.assertTrue(v["all_passed"])

    def test_fail_no_trades(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 0}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.99},
            mapping_validation={"monotonic": True, "passes_risk_gate_at_frozen_ceiling": True},
            latency_report={"increase_ratio": 0.01},
            range_safety={"checksum_unchanged": True},
            trend_safety={"checksum_unchanged": True},
        )
        self.assertFalse(v["all_passed"])


class TestSafetyGuards(unittest.TestCase):
    def test_no_riskgate_edit(self):
        src = (PKG / "production_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("MIN_CONFIDENCE_FOR_RISK", src)
        self.assertNotIn("RiskPolicy(", src)

    def test_factory_uses_mapper(self):
        src = (ROOT / "tradingbot" / "ml" / "integration" / "factory.py").read_text(encoding="utf-8")
        self.assertIn("build_mapped_production_risk", src)

    def test_no_kernel_touch(self):
        for name in PKG.glob("*.py"):
            self.assertNotIn("TradingKernel", name.read_text(encoding="utf-8"))


class TestPackageStructure(unittest.TestCase):
    def test_modules_exist(self):
        names = [
            "mapping_types.py", "confidence_mapper.py", "mapping_curve.py",
            "equivalence_solver.py", "mapping_validator.py", "production_adapter.py",
            "mapping_trace.py", "orchestrator.py", "report_generator.py", "validator.py",
        ]
        for n in names:
            self.assertTrue((PKG / n).is_file(), n)


class TestAstParse(unittest.TestCase):
    def test_all_parse(self):
        for p in PKG.glob("*.py"):
            ast.parse(p.read_text(encoding="utf-8"))


class TestMappingCurveLookup(unittest.TestCase):
    def test_lookup_table(self):
        from tradingbot.ml.confidence_mapping.mapping_curve import curve_lookup_table
        rows = curve_lookup_table(_curve(), steps=5)
        self.assertEqual(len(rows), 6)


class TestEquivalenceSolver(unittest.TestCase):
    def test_load_anchors(self):
        from tradingbot.ml.confidence_mapping.equivalence_solver import load_phase15g_anchors
        a = load_phase15g_anchors()
        self.assertIn("frozen_ceiling", a)


class TestInitExports(unittest.TestCase):
    def test_exports(self):
        from tradingbot.ml.confidence_mapping import build_confidence_mapper, run_phase15h_mapping
        self.assertTrue(callable(build_confidence_mapper))
        self.assertTrue(callable(run_phase15h_mapping))


class TestOrchestratorMocked(unittest.TestCase):
    def test_run_mocked(self):
        from tradingbot.ml.confidence_mapping.orchestrator import run_phase15h_mapping
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tradingbot.ml.confidence_mapping.orchestrator.CandleStore") as cs:
                import pandas as pd
                cs.return_value.load.return_value = pd.DataFrame(
                    {"close": [1.0]}, index=pd.DatetimeIndex(["2025-01-01"], tz="UTC"),
                )
                with mock.patch("tradingbot.ml.confidence_mapping.orchestrator.DatasetStore") as ds:
                    ds.return_value.load_v2.return_value = pd.DataFrame(
                        {"timestamp": ["2025-01-01"], "f": [1.0]},
                    )
                    with mock.patch(
                        "tradingbot.ml.confidence_mapping.orchestrator.solve_mapping_curve",
                        return_value=_curve(),
                    ):
                        with mock.patch(
                            "tradingbot.ml.confidence_mapping.orchestrator.collect_empirical_pairs",
                            return_value=[(0.49, 0.76)],
                        ):
                            with mock.patch(
                                "tradingbot.ml.confidence_mapping.orchestrator.validate_mapping_curve",
                                return_value={
                                    "monotonic": True,
                                    "passes_risk_gate_at_frozen_ceiling": True,
                                },
                            ):
                                with mock.patch(
                                    "tradingbot.ml.confidence_mapping.orchestrator.replay_mapped_production",
                                    return_value={
                                        "windows": {
                                            "30d": {
                                                "actionable_signals": 50,
                                                "latency": {"warm_p95_ms": 100.0},
                                            },
                                        },
                                        "primary_days": 30,
                                    },
                                ):
                                    with mock.patch(
                                        "tradingbot.ml.confidence_mapping.orchestrator.compare_research_parity",
                                        return_value={"parity_rate": 0.99},
                                    ):
                                        with mock.patch(
                                            "tradingbot.ml.confidence_mapping.orchestrator.audit_range_safety",
                                            return_value={"checksum_unchanged": True},
                                        ):
                                            with mock.patch(
                                                "tradingbot.ml.confidence_mapping.orchestrator.audit_trend_safety",
                                                return_value={"checksum_unchanged": True},
                                            ):
                                                r = run_phase15h_mapping(base_dir=tmp, days=30)
        self.assertEqual(r.recommendation, "READY_FOR_PHASE15I")


class TestPchipContinuity(unittest.TestCase):
    def test_no_large_jumps(self):
        m = ConfidenceMapper(_curve())
        grid = np.linspace(0, 0.50144, 50)
        vals = [m.map(float(x)) for x in grid]
        jumps = [abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)]
        self.assertLess(max(jumps), 0.5)


class TestMappingTrace(unittest.TestCase):
    def test_trace_keys(self):
        from tradingbot.ml.confidence_mapping.mapping_trace import build_mapping_trace
        t = build_mapping_trace(frozen=0.49, mapped=0.75)
        self.assertIn("mapped_confidence", t)


class TestMappingTypes(unittest.TestCase):
    def test_curve_to_dict(self):
        d = _curve().to_dict()
        self.assertEqual(d["method"], "pchip")


class TestResearchParityCallable(unittest.TestCase):
    def test_import(self):
        from tradingbot.ml.confidence_mapping.research_parity import compare_research_parity
        self.assertTrue(callable(compare_research_parity))


class TestProductionReplayCallable(unittest.TestCase):
    def test_import(self):
        from tradingbot.ml.confidence_mapping.production_replay import replay_mapped_production
        self.assertTrue(callable(replay_mapped_production))


class TestSafetyAuditCallable(unittest.TestCase):
    def test_range(self):
        from tradingbot.ml.confidence_mapping.safety_audit import audit_range_safety
        self.assertTrue(callable(audit_range_safety))


class TestCliExists(unittest.TestCase):
    def test_script(self):
        p = ROOT / "scripts" / "run_phase15h_confidence_mapping.py"
        self.assertTrue(p.is_file())


class TestMapperResult(unittest.TestCase):
    def test_map_result(self):
        r = ConfidenceMapper(_curve()).map_result(0.5)
        self.assertGreater(r.mapped_confidence, r.frozen_confidence)


class TestFactoryStackType(unittest.TestCase):
    def test_build_stack(self):
        from tradingbot.ml.integration.factory import build_ml_kernel_stack
        with mock.patch("tradingbot.ml.integration.factory.PipelineCache"):
            with mock.patch("tradingbot.ml.integration.factory.build_production_calibrated_adapter"):
                with mock.patch("tradingbot.ml.integration.factory.build_mapped_production_risk") as b:
                    b.return_value = mock.Mock()
                    with mock.patch("tradingbot.ml.integration.factory.TradeQualityAdapter"):
                        stack = build_ml_kernel_stack()
        self.assertIsNotNone(stack)


class TestSolveMappingCurve(unittest.TestCase):
    def test_solve_from_pairs(self):
        from tradingbot.ml.confidence_mapping.equivalence_solver import solve_mapping_curve
        curve = solve_mapping_curve([(0.3, 0.5), (0.5, 0.77)])
        self.assertGreater(curve.frozen_ceiling, 0)

    def test_monotone_anchors(self):
        from tradingbot.ml.confidence_mapping.equivalence_solver import solve_mapping_curve
        curve = solve_mapping_curve([(0.4, 0.6), (0.3, 0.7)])
        ys = [a.research for a in curve.anchors]
        self.assertEqual(ys, sorted(ys))


class TestBuildMappingCurve(unittest.TestCase):
    def test_report_context(self):
        from tradingbot.ml.confidence_mapping.mapping_curve import build_mapping_report_context
        ctx = build_mapping_report_context(_curve())
        self.assertIn("lookup_table", ctx)


class TestConfidenceMapperDict(unittest.TestCase):
    def test_to_dict(self):
        d = ConfidenceMapper(_curve()).to_dict()
        self.assertTrue(d["monotonic"])


class TestMappedAdapterEvaluate(unittest.TestCase):
    def test_evaluate_maps_before_risk(self):
        from tradingbot.ml.decision_engine.decision_types import MarketContext, EngineSignal
        cal_mock = mock.Mock()
        cal_mock.decide.return_value = mock.Mock(
            final_confidence=0.49, final_action="SELL",
            decision=mock.Mock(engine="trend_rf_v40", regime="TREND", timestamp=mock.Mock()),
            raw_confidence=mock.Mock(engine_signal="SELL"),
            calibrated=mock.Mock(), calibration_trace={},
        )
        risk_engine = mock.Mock()
        risk_engine.recommend.return_value = mock.Mock(allowed=True, risk_percent=0.1)
        mapper = ConfidenceMapper(_curve())
        adapter = MappedProductionRiskAdapter(cal_mock, mapper, risk_engine=risk_engine)
        ctx = MarketContext(
            symbol="X", timeframe="M5", features={}, regime="TREND", regime_strength=0.8,
            range_signal=EngineSignal("HOLD", 0, "phase9_9", 0, {}),
            trend_signal=EngineSignal("SELL", 0.5, "trend_rf_v40", 0.4, {}),
            volatility=50.0, session="london",
        )
        mapped_cal, risk = adapter.evaluate(ctx)
        self.assertGreater(mapped_cal.final_confidence, 0.49)
        self.assertTrue(risk.allowed)


class TestValidatorChecks(unittest.TestCase):
    def test_failed_list(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 0}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.5},
            mapping_validation={"monotonic": False, "passes_risk_gate_at_frozen_ceiling": False},
            latency_report={"increase_ratio": 0.2},
            range_safety={"checksum_unchanged": False},
            trend_safety={"checksum_unchanged": False},
        )
        self.assertGreater(len(v["failed"]), 0)


class TestReportsDir(unittest.TestCase):
    def test_path(self):
        from tradingbot.ml.confidence_mapping.config import reports_dir
        self.assertIn("phase15h", str(reports_dir()))


class TestPhase15HResult(unittest.TestCase):
    def test_to_dict(self):
        from tradingbot.ml.confidence_mapping.orchestrator import Phase15HResult
        d = Phase15HResult("PASS", "READY_FOR_PHASE15I", "/tmp").to_dict()
        self.assertEqual(d["phase"], "15H")


class TestMappingExamples(unittest.TestCase):
    def test_frozen_30_maps_up(self):
        m = ConfidenceMapper(_curve())
        self.assertGreater(m.map(0.30), 0.30)

    def test_identity_near_zero(self):
        m = ConfidenceMapper(_curve())
        self.assertLess(m.map(0.01), 0.1)


class TestPairErrorValidation(unittest.TestCase):
    def test_with_pairs(self):
        m = ConfidenceMapper(_curve())
        v = validate_mapping_curve(m, pairs=[(0.49, 0.75), (0.50, 0.76)])
        self.assertIsNotNone(v["mean_pair_error"])


class TestBuildConfidenceMapperFallback(unittest.TestCase):
    def test_empty_data_fallback(self):
        from tradingbot.ml.confidence_mapping.production_adapter import build_confidence_mapper
        with mock.patch("tradingbot.ml.confidence_mapping.production_adapter.CandleStore") as cs:
            cs.return_value.load.return_value = None
            with mock.patch("tradingbot.ml.confidence_mapping.production_adapter.DatasetStore") as ds:
                ds.return_value.load_v2.return_value = None
                m = build_confidence_mapper()
        self.assertGreater(m.map(0.50144), 0.55)


class TestSafetyAuditTrend(unittest.TestCase):
    def test_trend_callable(self):
        from tradingbot.ml.confidence_mapping.safety_audit import audit_trend_safety
        self.assertTrue(callable(audit_trend_safety))


class TestConfigDefaults(unittest.TestCase):
    def test_stride(self):
        from tradingbot.ml.confidence_mapping.config import DEFAULT_STRIDE
        self.assertEqual(DEFAULT_STRIDE, 10)


class TestFinalReportRoundtrip(unittest.TestCase):
    def test_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15h_reports(
                mapping_curve={}, mapping_validation={}, research_vs_production={},
                production_replay={}, latency_report={}, range_safety={},
                trend_safety={}, final_report={"recommendation": "READY_FOR_PHASE15I"},
                base_dir=tmp,
            )
            data = json.loads((out / "phase15h_final_report.json").read_text())
            self.assertEqual(data["recommendation"], "READY_FOR_PHASE15I")


class TestAdditionalCoverage(unittest.TestCase):
    def test_mapping_result_to_dict(self):
        from tradingbot.ml.confidence_mapping.mapping_types import MappingResult
        d = MappingResult(0.49, 0.76).to_dict()
        self.assertEqual(d["frozen_confidence"], 0.49)

    def test_anchor_frozen(self):
        a = MappingAnchor(0.5, 0.77, "test")
        self.assertEqual(a.frozen, 0.5)

    def test_continuous_flag(self):
        v = validate_mapping_curve(ConfidenceMapper(_curve()))
        self.assertTrue(v["continuous"])

    def test_discontinuity_zero(self):
        v = validate_mapping_curve(ConfidenceMapper(_curve()))
        self.assertEqual(v["discontinuity_count"], 0)

    def test_mapped_ceiling_field(self):
        v = validate_mapping_curve(ConfidenceMapper(_curve()))
        self.assertGreater(v["mapped_ceiling"], 0.55)

    def test_riskgate_unchanged_check(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 1}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.99},
            mapping_validation={"monotonic": True, "passes_risk_gate_at_frozen_ceiling": True},
            latency_report={"increase_ratio": 0.0},
            range_safety={"checksum_unchanged": True},
            trend_safety={"checksum_unchanged": True},
        )
        self.assertTrue(v["checks"]["riskgate_unchanged"])

    def test_bundle_unchanged_check(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 1}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.99},
            mapping_validation={"monotonic": True, "passes_risk_gate_at_frozen_ceiling": True},
            latency_report={"increase_ratio": 0.0},
            range_safety={"checksum_unchanged": True},
            trend_safety={"checksum_unchanged": True},
        )
        self.assertTrue(v["checks"]["bundle_unchanged"])

    def test_latency_budget_check(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 1}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.99},
            mapping_validation={"monotonic": True, "passes_risk_gate_at_frozen_ceiling": True},
            latency_report={"increase_ratio": 0.04},
            range_safety={"checksum_unchanged": True},
            trend_safety={"checksum_unchanged": True},
        )
        self.assertTrue(v["checks"]["latency_within_budget"])

    def test_parity_check(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 1}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.985},
            mapping_validation={"monotonic": True, "passes_risk_gate_at_frozen_ceiling": True},
            latency_report={"increase_ratio": 0.0},
            range_safety={"checksum_unchanged": True},
            trend_safety={"checksum_unchanged": True},
        )
        self.assertTrue(v["checks"]["parity_above_target"])

    def test_production_trades_check(self):
        v = validate_phase15h(
            production_replay={"windows": {"180d": {"actionable_signals": 5}}, "primary_days": 180},
            research_vs_production={"parity_rate": 0.99},
            mapping_validation={"monotonic": True, "passes_risk_gate_at_frozen_ceiling": True},
            latency_report={"increase_ratio": 0.0},
            range_safety={"checksum_unchanged": True},
            trend_safety={"checksum_unchanged": True},
        )
        self.assertTrue(v["checks"]["production_produces_trades"])

    def test_build_mapped_production_risk(self):
        from tradingbot.ml.confidence_mapping.production_adapter import build_mapped_production_risk
        with mock.patch(
            "tradingbot.ml.confidence_mapping.production_adapter.build_confidence_mapper",
            return_value=ConfidenceMapper(_curve()),
        ):
            a = build_mapped_production_risk(mock.Mock())
        self.assertIsInstance(a, MappedProductionRiskAdapter)

    def test_collect_pairs_callable(self):
        from tradingbot.ml.confidence_mapping.equivalence_solver import collect_empirical_pairs
        self.assertTrue(callable(collect_empirical_pairs))


if __name__ == "__main__":
    unittest.main()
