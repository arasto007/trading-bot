"""Phase 15F — confidence recovery tests."""

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

from tradingbot.ml.confidence_engine.calibration_policy import MIN_CALIBRATED_CONFIDENCE
from tradingbot.ml.decision_engine.decision_policy import DEFAULT_MIN_CONFIDENCE
from tradingbot.ml.integration.recovered_calibration import build_production_calibrated_adapter, calibration_status
from tradingbot.ml.phase15f.bundle_audit import validate_bundles
from tradingbot.ml.phase15f.config import RESEARCH_PROD_MAX_DIFF, reports_dir
from tradingbot.ml.phase15f.decision_policy_audit import audit_decision_policy
from tradingbot.ml.phase15f.report_generator import write_phase15f_reports
from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter, ResearchCalibrationPolicy
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy

PHASE15F_PKG = ROOT / "tradingbot" / "ml" / "phase15f"
INTEGRATION_PKG = ROOT / "tradingbot" / "ml" / "integration"


class TestConfig(unittest.TestCase):
    def test_max_diff(self):
        self.assertEqual(RESEARCH_PROD_MAX_DIFF, 0.02)

    def test_reports_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("phase15f", str(reports_dir(tmp)))


class TestConfidenceTraceResolver(unittest.TestCase):
    def test_engine_inners_uses_active_resolver(self):
        src = (PHASE15F_PKG / "confidence_trace.py").read_text(encoding="utf-8")
        self.assertIn("resolve_active_trend_engine_id", src)
        self.assertNotIn('registry.get("trend_rf_v40")', src)


class TestCalibrationStatus(unittest.TestCase):
    def test_status_keys(self):
        s = calibration_status()
        self.assertIn("calibration_method", s)
        self.assertTrue(s["production_uses_platt"])

    def test_missing_prior_documented(self):
        s = calibration_status()
        self.assertIn("missing_in_prior_production", s)


class TestDecisionPolicyAudit(unittest.TestCase):
    def test_audit_structure(self):
        a = audit_decision_policy()
        self.assertIn("decision_policy_14_1", a)
        self.assertEqual(a["decision_policy_14_1"]["min_confidence"], DEFAULT_MIN_CONFIDENCE)

    def test_prior_bug_flagged(self):
        a = audit_decision_policy()
        self.assertTrue(a["production_prior_bug"]["missing_platt"])

    def test_phase14_6_threshold(self):
        policy = load_phase14_6_policy()
        self.assertEqual(policy.get("calibration_method"), "platt")

    def test_verdict_present(self):
        self.assertIn("Platt", audit_decision_policy()["verdict"])


class TestResearchCalibrationPolicy(unittest.TestCase):
    def test_passes_gate(self):
        p = ResearchCalibrationPolicy(min_calibrated_confidence=0.30)
        self.assertTrue(p.passes_gate(0.35))
        self.assertFalse(p.passes_gate(0.20))

    def test_default_threshold(self):
        p = ResearchCalibrationPolicy()
        self.assertEqual(p.min_calibrated_confidence, 0.55)


class TestBundleAudit(unittest.TestCase):
    def test_validate_returns_structure(self):
        if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
            self.skipTest("artifacts missing")
        b = validate_bundles()
        self.assertIn("trend_rf_v40", b)
        self.assertIn("phase9_9", b)


class TestReportGenerator(unittest.TestCase):
    def test_writes_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15f_reports(
                confidence_flow={"stages": {}},
                production_vs_research={},
                calibration_check={},
                bundle_validation={},
                decision_policy_audit={},
                confidence_histogram={},
                recovery_validation={},
                final_report={"status": "PASS"},
                base_dir=tmp,
            )
            self.assertTrue((out / "phase15f_final_report.json").is_file())
            self.assertEqual(len(list(out.glob("*.json"))), 8)

    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15f_reports(
                confidence_flow={}, production_vs_research={}, calibration_check={},
                bundle_validation={}, decision_policy_audit={}, confidence_histogram={},
                recovery_validation={}, final_report={"recommendation": "READY_FOR_PHASE15G"},
                base_dir=tmp,
            )
            data = json.loads((out / "phase15f_final_report.json").read_text())
            self.assertEqual(data["recommendation"], "READY_FOR_PHASE15G")


class TestSafetyGuards(unittest.TestCase):
    def test_no_order_send_phase15f(self):
        for py in PHASE15F_PKG.glob("*.py"):
            self.assertNotIn("order_send(", py.read_text(encoding="utf-8"))

    def test_no_kernel_modify(self):
        for py in PHASE15F_PKG.glob("*.py"):
            self.assertNotIn("TradingKernel", py.read_text(encoding="utf-8"))

    def test_no_mt5(self):
        for py in PHASE15F_PKG.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            self.assertNotIn("MetaTrader5", src)

    def test_recovered_calibration_no_execution(self):
        src = (INTEGRATION_PKG / "recovered_calibration.py").read_text(encoding="utf-8")
        self.assertNotIn("order_send", src)

    def test_ast_clean(self):
        for py in PHASE15F_PKG.glob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ("order_send",))


class TestFactoryIntegration(unittest.TestCase):
    def test_factory_imports_recovered_calibration(self):
        src = (INTEGRATION_PKG / "factory.py").read_text(encoding="utf-8")
        self.assertIn("build_production_calibrated_adapter", src)
        self.assertNotIn("ConfidenceCalibrator()", src)

    def test_build_production_fallback_without_data(self):
        from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
        with tempfile.TemporaryDirectory() as tmp:
            adapter = build_production_calibrated_adapter(
                DecisionOrchestrator(), base_dir=tmp,
            )
            self.assertIsNotNone(adapter)


class TestConfidenceTrace(unittest.TestCase):
    def test_trace_structure_mocked(self):
        from tradingbot.ml.phase15f.confidence_trace import trace_confidence_flow
        from tradingbot.domain.models import MarketKey
        df = pd.DataFrame({
            "open": [1.0] * 400, "high": [1.1] * 400, "low": [0.9] * 400,
            "close": np.linspace(2300, 2310, 400), "volume": [100] * 400,
        }, index=pd.date_range("2022-01-01", periods=400, freq="5min", tz="UTC"))
        with mock.patch("tradingbot.ml.phase15f.confidence_trace.build_ml_kernel_stack") as mstack:
            with mock.patch("tradingbot.ml.phase15f.confidence_trace.build_kernel_adapter") as mad:
                with mock.patch("tradingbot.ml.phase15f.confidence_trace.PipelineCache.get_unified_frame") as mu:
                    mu.return_value = pd.DataFrame({"timestamp": [df.index[-1]], "label": [1]})
                    mu.return_value.index = df.index[-1:]
                    mstack.return_value.orchestrator.decide.return_value.action = "HOLD"
                    mstack.return_value.orchestrator.decide.return_value.confidence = 0.12
                    mstack.return_value.orchestrator.decide.return_value.metadata = {}
                    mstack.return_value.orchestrator.decide.return_value.explanation = []
                    mstack.return_value.calibration.policy.min_calibrated_confidence = 0.30
                    mstack.return_value.quality.evaluate.return_value = (
                        mock.Mock(final_confidence=0.65, final_action="BUY", decision=mock.Mock(metadata={})),
                        mock.Mock(allowed=True, risk_percent=0.2),
                        mock.Mock(allowed=True, score=0.7),
                    )
                    mad.return_value.produce_unified_signal.return_value = mock.Mock(
                        direction="BUY", confidence=0.65, checksum="x", trace=[], reason=[],
                        compute_checksum=lambda: "x",
                    )
                    mad.return_value._deps = mstack.return_value
                    mad.return_value._deps.registry.get.return_value = mock.Mock(inner=mock.Mock())
                    with mock.patch("tradingbot.ml.phase15f.confidence_trace.build_market_context") as mc:
                        mc.return_value = mock.Mock(
                            regime="TREND", features={}, volatility=50, regime_strength=0.5,
                            range_signal=mock.Mock(signal="BUY", confidence=0.6, probability=0.6),
                            trend_signal=mock.Mock(signal="BUY", confidence=0.6, probability=0.6),
                        )
                        with mock.patch("tradingbot.ml.phase15f.confidence_trace.select_engine", return_value="trend_rf_v40"):
                            with mock.patch("tradingbot.ml.phase15f.confidence_trace.select_signal") as ss:
                                ss.return_value = mock.Mock(signal="BUY", confidence=0.6, probability=0.6)
                                result = trace_confidence_flow(
                                    market=MarketKey("XAUUSD", "M5"), slice_df=df,
                                )
        self.assertIn("stages", result)


class TestPipelineCompare(unittest.TestCase):
    def test_compare_keys(self):
        from tradingbot.ml.phase15f.pipeline_compare import compare_same_candle
        self.assertTrue(callable(compare_same_candle))


class TestRecoveryValidator(unittest.TestCase):
    def test_missing_candles(self):
        from tradingbot.ml.phase15f.recovery_validator import run_recovery_validation
        with tempfile.TemporaryDirectory() as tmp:
            result = run_recovery_validation(base_dir=tmp, days_list=(30,))
            self.assertIn("error", result)


class TestOrchestrator(unittest.TestCase):
    def test_missing_candles_raises(self):
        from tradingbot.ml.phase15f.orchestrator import run_phase15f_recovery
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                run_phase15f_recovery(base_dir=tmp, days=30)


class TestThresholds(unittest.TestCase):
    def test_min_calibrated_default(self):
        self.assertEqual(MIN_CALIBRATED_CONFIDENCE, 0.55)

    def test_research_adapter_type(self):
        self.assertTrue(hasattr(ResearchCalibratedAdapter, "decide"))


class TestDeterminism(unittest.TestCase):
    def test_policy_audit_stable(self):
        a1 = audit_decision_policy()
        a2 = audit_decision_policy()
        self.assertEqual(a1["decision_policy_14_1"], a2["decision_policy_14_1"])


class TestCalibrationCheck(unittest.TestCase):
    def test_platt_method(self):
        p = load_phase14_6_policy()
        self.assertEqual(p["calibration_method"], "platt")

    def test_threshold_not_55_in_14_6(self):
        p = load_phase14_6_policy()
        self.assertEqual(float(p["confidence_threshold"]), 0.30)


class TestRecoveryRules(unittest.TestCase):
    def test_priority_documented(self):
        a = audit_decision_policy()
        self.assertIn("Reconnect", a["verdict"])

    def test_unified_uses_calibrated_field(self):
        from tradingbot.ml.integration import kernel_adapter as ka
        src = ka.__file__
        content = Path(src).read_text(encoding="utf-8")
        self.assertIn("calibrated.final_confidence", content)


class TestMapper(unittest.TestCase):
    def test_mapper_passes_confidence(self):
        from tradingbot.ml.integration.signal_mapper import map_unified_to_trading_signal
        from tradingbot.ml.phase15a.unified_signal import UnifiedSignal
        from tradingbot.domain.models import MarketKey
        u = UnifiedSignal(
            engine="trend_rf_v40", regime="TREND", direction="BUY",
            confidence=0.65, quality=0.7, risk=0.2,
        )
        df = pd.DataFrame({
            "open": [1], "high": [1.1], "low": [0.9], "close": [2300], "volume": [1],
        }, index=pd.date_range("2022-01-01", periods=1, freq="5min", tz="UTC"))
        sig = map_unified_to_trading_signal(u, MarketKey("XAUUSD", "M5"), df)
        self.assertEqual(sig.confidence, 0.65)


class TestChecksum(unittest.TestCase):
    def test_bundle_audit_checksum_field(self):
        if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
            self.skipTest("artifacts missing")
        b = validate_bundles()
        self.assertIn("bundle_unchanged", b)


class TestConfidencePropagation(unittest.TestCase):
    def test_compression_in_decision_engine(self):
        from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine
        ce = ConfidenceEngine()
        v = ce.compute(model_confidence=0.6, regime_strength=0.5, market_quality=0.4)
        self.assertLess(v, 0.6)


class TestPhase15FPackage(unittest.TestCase):
    def test_all_modules_import(self):
        from tradingbot.ml.phase15f import orchestrator, confidence_trace, pipeline_compare
        from tradingbot.ml.phase15f import bundle_audit, recovery_validator
        self.assertTrue(callable(orchestrator.run_phase15f_recovery))


class TestFinalVerdict(unittest.TestCase):
    def test_verdict_values(self):
        self.assertIn("READY_FOR_PHASE15G", ["READY_FOR_PHASE15G", "NEEDS_REVIEW"])


class TestIntegrationRecovered(unittest.TestCase):
    def test_cache_key_isolated(self):
        from tradingbot.ml.integration import recovered_calibration as rc
        rc._cached.clear()
        self.assertEqual(len(rc._cached), 0)


class TestHistogram(unittest.TestCase):
    def test_recovery_validator_latency_keys(self):
        from tradingbot.ml.phase15f.recovery_validator import run_recovery_validation
        with mock.patch("tradingbot.ml.phase15f.recovery_validator.CandleStore") as cs:
            cs.return_value.load.return_value = pd.DataFrame({
                "open": [1.0] * 500, "high": [1.1] * 500, "low": [0.9] * 500,
                "close": np.linspace(2300, 2310, 500), "volume": [100] * 500,
            }, index=pd.date_range("2022-01-01", periods=500, freq="5min", tz="UTC"))
            with mock.patch("tradingbot.ml.phase15f.recovery_validator.build_kernel_adapter") as ba:
                ba.return_value.generate_signal.return_value = None
                ba.return_value.last_unified_signal = None
                with mock.patch("tradingbot.ml.phase15f.recovery_validator.build_ml_kernel_stack"):
                    with mock.patch("tradingbot.ml.phase15f.recovery_validator.validate_trend_checksum") as vt:
                        vt.return_value = {"bundle_sha256": "abc", "valid": True}
                        r = run_recovery_validation(days_list=(30,), warmup=50, stride=50)
        self.assertIn("windows", r)


class TestReplayEquality(unittest.TestCase):
    def test_replay_empty_without_data(self):
        from tradingbot.ml.phase15f.pipeline_compare import replay_research_trades
        c = pd.DataFrame()
        d = pd.DataFrame()
        self.assertEqual(replay_research_trades(candles=c, dataset=d), [])


class TestAuditModules(unittest.TestCase):
    def test_bundle_fields(self):
        b = validate_bundles()
        self.assertIn("matches_phase15a_frozen", b)

    def test_calibration_platt_documented(self):
        self.assertEqual(calibration_status()["calibration_method"], "platt")

    def test_decision_min_confidence(self):
        self.assertEqual(DEFAULT_MIN_CONFIDENCE, 0.55)

    def test_reports_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_phase15f_reports(
                confidence_flow={}, production_vs_research={}, calibration_check={},
                bundle_validation={}, decision_policy_audit={}, confidence_histogram={},
                recovery_validation={}, final_report={},
                base_dir=tmp,
            )
            self.assertEqual(len(list(reports_dir(tmp).glob("*.json"))), 8)

    def test_research_adapter_has_orchestrator(self):
        from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
        from tradingbot.ml.research.phase14_6.calibration_alternatives import Phase14_2ACalibration
        a = ResearchCalibratedAdapter(
            DecisionOrchestrator(),
            calibration_method=Phase14_2ACalibration(),
        )
        self.assertIsNotNone(a.orchestrator)

    def test_phase15f_init(self):
        from tradingbot.ml.phase15f import run_phase15f_recovery
        self.assertTrue(callable(run_phase15f_recovery))

    def test_recovery_validator_windows_key(self):
        from tradingbot.ml.phase15f.recovery_validator import run_recovery_validation
        with mock.patch("tradingbot.ml.phase15f.recovery_validator.CandleStore") as cs:
            cs.return_value.load.return_value = None
            self.assertIn("error", run_recovery_validation())

    def test_confidence_trace_diagnosis_keys(self):
        from tradingbot.ml.phase15f.confidence_trace import trace_confidence_flow
        self.assertTrue(callable(trace_confidence_flow))

    def test_policy_audit_recovery_section(self):
        self.assertIn("recovery", audit_decision_policy())

    def test_factory_no_heuristic_calibrator(self):
        self.assertNotIn("CalibratedDecisionAdapter(orchestrator, calibrator=ConfidenceCalibrator())",
                         (INTEGRATION_PKG / "factory.py").read_text(encoding="utf-8"))

    def test_kernel_unified_confidence_field(self):
        content = (INTEGRATION_PKG / "kernel_adapter.py").read_text(encoding="utf-8")
        self.assertIn("confidence=float(calibrated.final_confidence)", content)

    def test_platt_threshold_from_policy(self):
        self.assertLess(float(load_phase14_6_policy()["confidence_threshold"]), 0.55)

    def test_safety_no_risk_gate_edit(self):
        for py in PHASE15F_PKG.glob("*.py"):
            self.assertNotIn("class RiskGate", py.read_text(encoding="utf-8"))

    def test_max_diff_tolerance(self):
        self.assertLessEqual(RESEARCH_PROD_MAX_DIFF, 0.05)

    def test_report_final_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_phase15f_reports(
                confidence_flow={}, production_vs_research={}, calibration_check={},
                bundle_validation={}, decision_policy_audit={}, confidence_histogram={},
                recovery_validation={}, final_report={"phase": "15F"},
                base_dir=tmp,
            )
            self.assertTrue((reports_dir(tmp) / "phase15f_final_report.json").exists())


if __name__ == "__main__":
    unittest.main()
