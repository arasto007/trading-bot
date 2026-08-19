"""Phase 15J — trend root cause tests (read-only diagnostic)."""

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

from tradingbot.ml.decision_engine.decision_types import EngineSignal, MarketContext
from tradingbot.ml.research.phase15j.config import (
    ENGINE_COLLAPSE_THRESHOLD,
    FEATURE_DRIFT_PSI_THRESHOLD,
    VALID_ROOT_CAUSES,
    VALID_STOP_STAGES,
)
from tradingbot.ml.research.phase15j.engine_probability_distribution import _dist_stats, _histogram
from tradingbot.ml.research.phase15j.recommendation_engine import build_recommendation
from tradingbot.ml.research.phase15j.report_generator import write_phase15j_reports
from tradingbot.ml.research.phase15j.root_cause_detector import detect_root_cause
from tradingbot.ml.research.phase15j.stage_loss_report import build_stage_loss_report
from tradingbot.ml.research.phase15j.trend_pipeline_trace import (
    TrendTraceRecord,
    _actionable,
    _detect_stop_stage,
)
from tradingbot.ml.research.phase15j.trend_signal_statistics import (
    _stage_index,
    _stage_pass_rate,
    compute_trend_statistics,
)
from tradingbot.ml.research.phase15j.validator import validate_phase15j

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase15j"


def _trace(**kwargs) -> dict:
    base = {
        "bars_traced": 10,
        "primary_stop_stage": "ENGINE",
        "stop_stage_counts": {"ENGINE": 10},
        "records": [{"stop_stage": "ENGINE", "trend_prediction": "HOLD"} for _ in range(10)],
    }
    base.update(kwargs)
    return base


class TestConfig(unittest.TestCase):
    def test_stop_stages(self):
        self.assertIn("ENGINE", VALID_STOP_STAGES)
        self.assertIn("NONE", VALID_STOP_STAGES)

    def test_root_causes(self):
        self.assertIn("ENGINE_COLLAPSE", VALID_ROOT_CAUSES)

    def test_engine_collapse_threshold(self):
        self.assertEqual(ENGINE_COLLAPSE_THRESHOLD, 0.05)


class TestActionable(unittest.TestCase):
    def test_buy(self):
        self.assertTrue(_actionable("BUY"))

    def test_hold(self):
        self.assertFalse(_actionable("HOLD"))


class TestStopStageDetection(unittest.TestCase):
    def test_engine_stop(self):
        s = _detect_stop_stage(
            engine_action="HOLD", decision_action="HOLD", calibrated_action="HOLD",
            mapped_ok=True, risk_allowed=False, quality_allowed=False,
            kernel_action="HOLD", final_signal="HOLD",
        )
        self.assertEqual(s, "ENGINE")

    def test_decision_stop(self):
        s = _detect_stop_stage(
            engine_action="BUY", decision_action="HOLD", calibrated_action="HOLD",
            mapped_ok=True, risk_allowed=False, quality_allowed=False,
            kernel_action="HOLD", final_signal="HOLD",
        )
        self.assertEqual(s, "DECISION")

    def test_none_pass(self):
        s = _detect_stop_stage(
            engine_action="BUY", decision_action="BUY", calibrated_action="BUY",
            mapped_ok=True, risk_allowed=True, quality_allowed=True,
            kernel_action="BUY", final_signal="BUY",
        )
        self.assertEqual(s, "NONE")


class TestTrendTraceRecord(unittest.TestCase):
    def test_to_dict(self):
        r = TrendTraceRecord(
            timestamp="t", symbol="X", regime="TREND", selected_engine="trend_rf_v40",
            trend_probability=0.5, trend_prediction="HOLD", raw_confidence=0.0,
            compressed_confidence=0.0, calibrated_confidence=0.0, mapped_confidence=None,
            risk_allowed=False, risk_reason=None, quality_allowed=False,
            quality_reason=None, kernel_signal="HOLD", final_signal="HOLD", stop_stage="ENGINE",
        )
        d = r.to_dict()
        self.assertEqual(d["stop_stage"], "ENGINE")


class TestStatistics(unittest.TestCase):
    def test_engine_collapse_flag(self):
        s = compute_trend_statistics(_trace())
        self.assertIn("ENGINE_COLLAPSE", s["flags"])

    def test_stage_index(self):
        self.assertGreater(_stage_index("DECISION"), _stage_index("ENGINE"))

    def test_pass_rate(self):
        records = [{"stop_stage": "NONE"}, {"stop_stage": "ENGINE"}]
        self.assertEqual(_stage_pass_rate(records, "ENGINE"), 0.5)


class TestProbabilityStats(unittest.TestCase):
    def test_dist_stats_empty(self):
        d = _dist_stats([])
        self.assertEqual(d["count"], 0)

    def test_histogram(self):
        h = _histogram([0.1, 0.5, 0.9])
        self.assertGreater(len(h), 0)

    def test_dist_stats_values(self):
        d = _dist_stats([0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertGreater(d["mean"], 0.0)


class TestStageLoss(unittest.TestCase):
    def test_funnel_stages(self):
        stats = compute_trend_statistics(_trace())
        loss = build_stage_loss_report(_trace(), stats)
        self.assertEqual(len(loss["funnel"]), 9)

    def test_final_signals_zero_on_collapse(self):
        stats = compute_trend_statistics(_trace())
        loss = build_stage_loss_report(_trace(), stats)
        self.assertEqual(loss["final_signals"], 0)


class TestRootCauseDetector(unittest.TestCase):
    def _detect(self, **kwargs):
        trace = _trace(**kwargs.get("trace", {}))
        stats = compute_trend_statistics(trace)
        prob = {"flags": [], "actionable_pct": 0.0, "all_probabilities": {}, "threshold": 0.4}
        drift = {"flags": [], "drifted_features": [], "feature_order_identical": True}
        loss = build_stage_loss_report(trace, stats)
        return detect_root_cause(
            trace_report=trace, statistics=stats, probability=prob,
            feature_drift=drift, stage_loss=loss,
        )

    def test_engine_collapse(self):
        r = self._detect()
        self.assertEqual(r["root_cause"], "ENGINE_COLLAPSE")

    def test_has_evidence(self):
        r = self._detect()
        self.assertTrue(r["causes"])

    def test_probability_collapse(self):
        trace = _trace(primary_stop_stage="ENGINE")
        stats = compute_trend_statistics(trace)
        prob = {"flags": ["PROBABILITY_COLLAPSE"], "actionable_pct": 0.01,
                "all_probabilities": {"max": 0.3}, "threshold": 0.4}
        drift = {"flags": [], "drifted_features": [], "feature_order_identical": True}
        loss = build_stage_loss_report(trace, stats)
        r = detect_root_cause(
            trace_report=trace, statistics=stats, probability=prob,
            feature_drift=drift, stage_loss=loss,
        )
        self.assertIn(r["root_cause"], ("PROBABILITY_COLLAPSE", "MULTIPLE", "ENGINE_COLLAPSE"))


class TestRecommendation(unittest.TestCase):
    def test_engine_recommendation(self):
        r = build_recommendation({"root_cause": "ENGINE_COLLAPSE"})
        self.assertEqual(r["recommendation"]["next_phase"], "Phase15K")

    def test_no_modify(self):
        r = build_recommendation({"root_cause": "RISK_GATE"})
        self.assertFalse(r["modifies_production"])

    def test_phase15k_stated(self):
        r = build_recommendation({"root_cause": "FEATURE_DRIFT"})
        self.assertIn("Phase15K", r["statement"])


class TestValidator(unittest.TestCase):
    def _valid(self):
        return validate_phase15j(
            trace_report={"primary_stop_stage": "ENGINE"},
            root_cause={"root_cause": "ENGINE_COLLAPSE", "causes": [{}],
                        "quantitative_summary": {"x": 1}},
            recommendation={"phase15k_investigation": "rule gate"},
            bundle_validation={"checksum_valid": True},
            feature_drift={"feature_order_identical": True},
        )

    def test_pass(self):
        self.assertTrue(self._valid()["all_passed"])

    def test_fail_no_stage(self):
        v = validate_phase15j(
            trace_report={"primary_stop_stage": "INVALID"},
            root_cause={"root_cause": "ENGINE_COLLAPSE", "causes": [{}],
                        "quantitative_summary": {}},
            recommendation={},
            bundle_validation={"checksum_valid": True},
            feature_drift={"feature_order_identical": True},
        )
        self.assertFalse(v["all_passed"])


class TestReportGenerator(unittest.TestCase):
    def test_writes_ten_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15j_reports(
                trend_pipeline_trace={"phase": "15J"},
                trend_statistics={"phase": "15J"},
                probability_distribution={"phase": "15J"},
                feature_drift={"phase": "15J"},
                bundle_validation={"phase": "15J"},
                adapter_validation={"phase": "15J"},
                stage_loss={"phase": "15J"},
                root_cause={"phase": "15J"},
                recommendation={"phase": "15J"},
                final_report={"status": "PASS"},
                base_dir=tmp,
            )
            self.assertEqual(len(list(out.glob("*.json"))), 10)


class TestModuleImports(unittest.TestCase):
    def test_trace(self):
        from tradingbot.ml.research.phase15j.trend_pipeline_trace import trace_trend_pipeline
        self.assertTrue(callable(trace_trend_pipeline))

    def test_orchestrator(self):
        from tradingbot.ml.research.phase15j.orchestrator import run_phase15j_rootcause
        self.assertTrue(callable(run_phase15j_rootcause))

    def test_bundle(self):
        from tradingbot.ml.research.phase15j.bundle_validation import validate_bundle
        self.assertTrue(callable(validate_bundle))

    def test_adapter(self):
        from tradingbot.ml.research.phase15j.adapter_validation import validate_adapter_chain
        self.assertTrue(callable(validate_adapter_chain))

    def test_feature_drift(self):
        from tradingbot.ml.research.phase15j.feature_drift import audit_feature_drift
        self.assertTrue(callable(audit_feature_drift))

    def test_probability(self):
        from tradingbot.ml.research.phase15j.engine_probability_distribution import analyze_probability_distribution
        self.assertTrue(callable(analyze_probability_distribution))


class TestPackageLayout(unittest.TestCase):
    def test_modules_exist(self):
        names = [
            "trend_pipeline_trace.py", "trend_signal_statistics.py",
            "engine_probability_distribution.py", "feature_drift.py",
            "bundle_validation.py", "adapter_validation.py", "stage_loss_report.py",
            "root_cause_detector.py", "recommendation_engine.py",
            "orchestrator.py", "report_generator.py", "validator.py", "config.py",
        ]
        for n in names:
            self.assertTrue((PKG / n).is_file(), n)

    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase15j_rootcause.py").is_file())


class TestSyntax(unittest.TestCase):
    def test_pkg_syntax(self):
        for py in PKG.glob("*.py"):
            ast.parse(py.read_text(encoding="utf-8"))


class TestOrchestratorMocked(unittest.TestCase):
    def test_run_mocked(self):
        from tradingbot.ml.research.phase15j.orchestrator import run_phase15j_rootcause
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tradingbot.ml.research.phase15j.orchestrator.CandleStore") as cs:
                cs.return_value.load.return_value = pd.DataFrame(
                    {"close": [1.0]}, index=pd.DatetimeIndex(["2025-01-01"], tz="UTC"),
                )
                with mock.patch("tradingbot.ml.research.phase15j.orchestrator.DatasetStore") as ds:
                    ds.return_value.load_v2.return_value = pd.DataFrame(
                        {"timestamp": ["2025-01-01"], "f": [1.0]},
                    )
                    with mock.patch(
                        "tradingbot.ml.research.phase15j.orchestrator.validate_bundle",
                        return_value={"checksum_valid": True},
                    ):
                        with mock.patch(
                            "tradingbot.ml.research.phase15j.orchestrator.trace_trend_pipeline",
                            return_value=_trace(),
                        ):
                            with mock.patch(
                                "tradingbot.ml.research.phase15j.orchestrator.analyze_probability_distribution",
                                return_value={"flags": ["ENGINE_COLLAPSE"], "actionable_pct": 0.0},
                            ):
                                with mock.patch(
                                    "tradingbot.ml.research.phase15j.orchestrator.audit_feature_drift",
                                    return_value={"feature_order_identical": True, "flags": []},
                                ):
                                    with mock.patch(
                                        "tradingbot.ml.research.phase15j.orchestrator.validate_adapter_chain",
                                        return_value={"no_information_loss": True},
                                    ):
                                        r = run_phase15j_rootcause(base_dir=tmp, days=30)
        self.assertEqual(r.status, "PASS")


class TestPsiThreshold(unittest.TestCase):
    def test_threshold_value(self):
        self.assertEqual(FEATURE_DRIFT_PSI_THRESHOLD, 0.25)


class TestStageOrder(unittest.TestCase):
    def test_kernel_before_none(self):
        self.assertLess(_stage_index("KERNEL"), _stage_index("NONE"))


class TestRecommendationMapping(unittest.TestCase):
    def test_all_causes_mapped(self):
        for cause in ("CALIBRATION", "RISK_GATE", "QUALITY_GATE", "DECISION_GATE"):
            r = build_recommendation({"root_cause": cause})
            self.assertEqual(r["recommendation"]["next_phase"], "Phase15K")


class TestTraceReportKeys(unittest.TestCase):
    def test_primary_stop(self):
        t = _trace(primary_stop_stage="ENGINE")
        self.assertEqual(t["primary_stop_stage"], "ENGINE")


class TestValidatorChecks(unittest.TestCase):
    def test_read_only_flags(self):
        v = validate_phase15j(
            trace_report={"primary_stop_stage": "ENGINE"},
            root_cause={"root_cause": "ENGINE_COLLAPSE", "causes": [{}],
                        "quantitative_summary": {"x": 1}},
            recommendation={"phase15k_investigation": "rule gate"},
            bundle_validation={"checksum_valid": True},
            feature_drift={"feature_order_identical": True},
        )
        self.assertTrue(v["checks"]["no_production_modifications"])
        self.assertTrue(v["checks"]["no_retraining"])


class TestDistStatsPercentiles(unittest.TestCase):
    def test_p99(self):
        vals = list(np.linspace(0, 1, 100))
        d = _dist_stats(vals)
        self.assertGreater(d["p99"], 0.9)


class TestHistogramBins(unittest.TestCase):
    def test_bin_count(self):
        h = _histogram([0.2, 0.4, 0.6], bins=5)
        self.assertEqual(len(h), 5)


class TestRootCauseMultiple(unittest.TestCase):
    def test_multiple_flags(self):
        trace = _trace()
        stats = {**compute_trend_statistics(trace), "flags": ["ENGINE_COLLAPSE"]}
        prob = {"flags": ["PROBABILITY_COLLAPSE"], "actionable_pct": 0.01,
                "all_probabilities": {"max": 0.2}, "threshold": 0.4}
        drift = {"flags": ["FEATURE_DRIFT"], "drifted_features": ["adx"],
                 "feature_order_identical": True, "psi_threshold": 0.25}
        loss = build_stage_loss_report(trace, stats)
        r = detect_root_cause(
            trace_report=trace, statistics=stats, probability=prob,
            feature_drift=drift, stage_loss=loss,
        )
        self.assertEqual(r["root_cause"], "MULTIPLE")


class TestReportsDir(unittest.TestCase):
    def test_path_suffix(self):
        from tradingbot.ml.research.phase15j.config import reports_dir
        self.assertTrue(str(reports_dir()).endswith("phase15j"))


class TestFinalReportFile(unittest.TestCase):
    def test_final_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15j_reports(
                trend_pipeline_trace={}, trend_statistics={},
                probability_distribution={}, feature_drift={},
                bundle_validation={}, adapter_validation={}, stage_loss={},
                root_cause={}, recommendation={}, final_report={"status": "PASS"},
                base_dir=tmp,
            )
            self.assertTrue((out / "phase15j_final_report.json").exists())


class TestCalibrationStop(unittest.TestCase):
    def test_calibration_stage(self):
        s = _detect_stop_stage(
            engine_action="BUY", decision_action="BUY", calibrated_action="HOLD",
            mapped_ok=True, risk_allowed=False, quality_allowed=False,
            kernel_action="HOLD", final_signal="HOLD",
        )
        self.assertEqual(s, "CALIBRATION")


class TestMappingStop(unittest.TestCase):
    def test_mapping_stage(self):
        s = _detect_stop_stage(
            engine_action="BUY", decision_action="BUY", calibrated_action="BUY",
            mapped_ok=False, risk_allowed=False, quality_allowed=False,
            kernel_action="HOLD", final_signal="HOLD",
        )
        self.assertEqual(s, "MAPPING")


class TestRiskStop(unittest.TestCase):
    def test_risk_stage(self):
        s = _detect_stop_stage(
            engine_action="BUY", decision_action="BUY", calibrated_action="BUY",
            mapped_ok=True, risk_allowed=False, quality_allowed=False,
            kernel_action="HOLD", final_signal="HOLD",
        )
        self.assertEqual(s, "RISK")


class TestQualityStop(unittest.TestCase):
    def test_quality_stage(self):
        s = _detect_stop_stage(
            engine_action="BUY", decision_action="BUY", calibrated_action="BUY",
            mapped_ok=True, risk_allowed=True, quality_allowed=False,
            kernel_action="HOLD", final_signal="HOLD",
        )
        self.assertEqual(s, "QUALITY")


class TestSellActionable(unittest.TestCase):
    def test_sell(self):
        self.assertTrue(_actionable("SELL"))


class TestStatisticsCounts(unittest.TestCase):
    def test_trend_bars(self):
        trace = _trace(records=[
            {"stop_stage": "ENGINE", "trend_prediction": "HOLD"},
            {"stop_stage": "ENGINE", "trend_prediction": "BUY"},
        ], bars_traced=2, stop_stage_counts={"ENGINE": 2})
        s = compute_trend_statistics(trace)
        self.assertEqual(s["trend_bars"], 2)
        self.assertEqual(s["trend_buy"], 1)


class TestFeatureDriftFlag(unittest.TestCase):
    def test_drift_root_cause(self):
        trace = _trace()
        stats = compute_trend_statistics(trace)
        prob = {"flags": [], "actionable_pct": 0.0, "all_probabilities": {}, "threshold": 0.4}
        drift = {"flags": ["FEATURE_DRIFT"], "drifted_features": ["adx"],
                 "feature_order_identical": True, "psi_threshold": 0.25}
        loss = build_stage_loss_report(trace, stats)
        r = detect_root_cause(
            trace_report=trace, statistics=stats, probability=prob,
            feature_drift=drift, stage_loss=loss,
        )
        self.assertIn(r["root_cause"], ("FEATURE_DRIFT", "MULTIPLE"))


class TestDecisionGateCause(unittest.TestCase):
    def test_decision_root(self):
        trace = _trace(primary_stop_stage="DECISION", stop_stage_counts={"DECISION": 5})
        stats = compute_trend_statistics(trace)
        prob = {"flags": [], "actionable_pct": 0.1, "all_probabilities": {}, "threshold": 0.4}
        drift = {"flags": [], "drifted_features": [], "feature_order_identical": True}
        loss = build_stage_loss_report(trace, stats)
        r = detect_root_cause(
            trace_report=trace, statistics=stats, probability=prob,
            feature_drift=drift, stage_loss=loss,
        )
        self.assertIn(r["root_cause"], ("DECISION_GATE", "ENGINE_COLLAPSE", "MULTIPLE"))


class TestRecommendationKernel(unittest.TestCase):
    def test_kernel_mapping(self):
        r = build_recommendation({"root_cause": "KERNEL_MAPPING"})
        self.assertIn("Kernel", r["recommendation"]["title"])


class TestRecommendationMultiple(unittest.TestCase):
    def test_multiple(self):
        r = build_recommendation({"root_cause": "MULTIPLE"})
        self.assertIn("Multi", r["recommendation"]["title"])


class TestValidatorBundleFail(unittest.TestCase):
    def test_checksum_fail(self):
        v = validate_phase15j(
            trace_report={"primary_stop_stage": "ENGINE"},
            root_cause={"root_cause": "ENGINE_COLLAPSE", "causes": [{}],
                        "quantitative_summary": {"x": 1}},
            recommendation={"phase15k_investigation": "x"},
            bundle_validation={"checksum_valid": False},
            feature_drift={"feature_order_identical": True},
        )
        self.assertFalse(v["checks"]["bundle_checksum_valid"])


class TestValidatorFeatureOrder(unittest.TestCase):
    def test_order_fail(self):
        v = validate_phase15j(
            trace_report={"primary_stop_stage": "ENGINE"},
            root_cause={"root_cause": "ENGINE_COLLAPSE", "causes": [{}],
                        "quantitative_summary": {"x": 1}},
            recommendation={"phase15k_investigation": "x"},
            bundle_validation={"checksum_valid": True},
            feature_drift={"feature_order_identical": False},
        )
        self.assertFalse(v["checks"]["feature_order_valid"])


class TestStageLossRouter(unittest.TestCase):
    def test_router_stage(self):
        stats = compute_trend_statistics(_trace())
        loss = build_stage_loss_report(_trace(), stats)
        self.assertEqual(loss["funnel"][0]["stage"], "Router")


class TestStageLossEngine(unittest.TestCase):
    def test_engine_loss(self):
        stats = compute_trend_statistics(_trace())
        loss = build_stage_loss_report(_trace(), stats)
        engine = next(s for s in loss["funnel"] if s["stage"] == "Engine")
        self.assertGreater(engine["loss"], 0)


class TestReportTraceFile(unittest.TestCase):
    def test_trace_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15j_reports(
                trend_pipeline_trace={"records": []}, trend_statistics={},
                probability_distribution={}, feature_drift={},
                bundle_validation={}, adapter_validation={}, stage_loss={},
                root_cause={}, recommendation={}, final_report={},
                base_dir=tmp,
            )
            self.assertTrue((out / "trend_pipeline_trace.json").exists())


class TestReportRootCauseFile(unittest.TestCase):
    def test_root_cause_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15j_reports(
                trend_pipeline_trace={}, trend_statistics={},
                probability_distribution={}, feature_drift={},
                bundle_validation={}, adapter_validation={}, stage_loss={},
                root_cause={"root_cause": "ENGINE_COLLAPSE"}, recommendation={},
                final_report={},
                base_dir=tmp,
            )
            data = json.loads((out / "root_cause.json").read_text(encoding="utf-8"))
            self.assertEqual(data["root_cause"], "ENGINE_COLLAPSE")


class TestConfigEngineId(unittest.TestCase):
    def test_trend_engine_id(self):
        from tradingbot.ml.research.phase15j.config import TREND_ENGINE_ID
        self.assertEqual(TREND_ENGINE_ID, "trend_rf_v40")


class TestConfigDefaults(unittest.TestCase):
    def test_default_days(self):
        from tradingbot.ml.research.phase15j.config import DEFAULT_DAYS
        self.assertEqual(DEFAULT_DAYS, 365)


class TestPassRateNone(unittest.TestCase):
    def test_all_pass(self):
        records = [{"stop_stage": "NONE"}] * 5
        self.assertEqual(_stage_pass_rate(records, "KERNEL"), 1.0)


class TestPassRateAllEngine(unittest.TestCase):
    def test_none_pass_engine(self):
        records = [{"stop_stage": "ENGINE"}] * 3
        self.assertEqual(_stage_pass_rate(records, "DECISION"), 0.0)


class TestRecommendationCalibration(unittest.TestCase):
    def test_calibration_rec(self):
        r = build_recommendation({"root_cause": "CALIBRATION"})
        self.assertIn("Calibration", r["recommendation"]["title"])


class TestRecommendationConfidenceMapping(unittest.TestCase):
    def test_mapping_rec(self):
        r = build_recommendation({"root_cause": "CONFIDENCE_MAPPING"})
        self.assertIn("Mapping", r["recommendation"]["title"])


class TestRecommendationProbability(unittest.TestCase):
    def test_probability_rec(self):
        r = build_recommendation({"root_cause": "PROBABILITY_COLLAPSE"})
        self.assertEqual(r["recommendation"]["next_phase"], "Phase15K")


class TestStatisticsPrimaryStop(unittest.TestCase):
    def test_primary(self):
        s = compute_trend_statistics(_trace(primary_stop_stage="ENGINE"))
        self.assertEqual(s["primary_stop_stage"], "ENGINE")


class TestTraceRecordMapped(unittest.TestCase):
    def test_mapped_field(self):
        r = TrendTraceRecord(
            timestamp="t", symbol="X", regime="TREND", selected_engine="trend_rf_v40",
            trend_probability=0.5, trend_prediction="HOLD", raw_confidence=0.0,
            compressed_confidence=0.0, calibrated_confidence=0.0, mapped_confidence=0.77,
            risk_allowed=False, risk_reason=None, quality_allowed=False,
            quality_reason=None, kernel_signal="HOLD", final_signal="HOLD", stop_stage="ENGINE",
        )
        self.assertEqual(r.to_dict()["mapped_confidence"], 0.77)


class TestDistStatsCount(unittest.TestCase):
    def test_count(self):
        self.assertEqual(_dist_stats([0.1, 0.2])["count"], 2)


class TestRootCauseQuantitative(unittest.TestCase):
    def test_summary_keys(self):
        r = detect_root_cause(
            trace_report=_trace(),
            statistics=compute_trend_statistics(_trace()),
            probability={"flags": [], "actionable_pct": 0, "all_probabilities": {}, "threshold": 0.4},
            feature_drift={"flags": [], "drifted_features": [], "feature_order_identical": True},
            stage_loss=build_stage_loss_report(_trace(), compute_trend_statistics(_trace())),
        )
        self.assertIn("trend_bars_traced", r["quantitative_summary"])


class TestValidatorPhase15k(unittest.TestCase):
    def test_phase15k_check(self):
        v = validate_phase15j(
            trace_report={"primary_stop_stage": "ENGINE"},
            root_cause={"root_cause": "ENGINE_COLLAPSE", "causes": [{}],
                        "quantitative_summary": {}},
            recommendation={"phase15k_investigation": ""},
            bundle_validation={"checksum_valid": True},
            feature_drift={"feature_order_identical": True},
        )
        self.assertFalse(v["checks"]["phase15k_direction_stated"])

    def test_phase15k_pass(self):
        v = validate_phase15j(
            trace_report={"primary_stop_stage": "ENGINE"},
            root_cause={"root_cause": "ENGINE_COLLAPSE", "causes": [{}],
                        "quantitative_summary": {"x": 1}},
            recommendation={"phase15k_investigation": "investigate rule gate"},
            bundle_validation={"checksum_valid": True},
            feature_drift={"feature_order_identical": True},
        )
        self.assertTrue(v["checks"]["phase15k_direction_stated"])


if __name__ == "__main__":
    unittest.main()
