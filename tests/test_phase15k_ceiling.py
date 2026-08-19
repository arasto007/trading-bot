"""Phase 15K — trend RF ceiling tests (read-only diagnostic)."""

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

from tradingbot.ml.research.phase15k.config import (
    OBSERVED_CEILING,
    PSI_CRITICAL,
    TREND_THRESHOLD,
    VALID_RECOMMENDATIONS,
    VALID_ROOT_CAUSES,
    dist_stats,
    pearson_corr,
    psi_score,
)
from tradingbot.ml.research.phase15k.recommendation_ceiling import build_ceiling_recommendation
from tradingbot.ml.research.phase15k.report_generator import write_phase15k_reports
from tradingbot.ml.research.phase15k.trend_ceiling_root_cause import detect_trend_ceiling_root_cause
from tradingbot.ml.research.phase15k.validator import validate_phase15k

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase15k"


def _ceiling(live_max=0.379, train_max=0.85):
    return {
        "live_trend_distribution": {"max": live_max},
        "training_distribution": {"max": train_max},
        "mathematical_bound": {"gap_to_threshold": TREND_THRESHOLD - live_max},
        "probability_shift_train_vs_live": {"max_delta": train_max - live_max},
    }


def _root_inputs(**overrides):
    base = {
        "ceiling": _ceiling(),
        "feature_impact": {"ceiling_breaking_features": ["adx"]},
        "distribution_drift": {"drift_critical_features": ["adx", "ema50_slope"], "per_feature": []},
        "model_behavior": {"flags": ["LOW_VARIANCE_LEAVES"], "tree_saturation": False, "path_collapse": False, "low_variance_leaves": True},
        "pipeline_audit": {"flags": [], "feature_order_identical": True, "bundle_vs_filter_max_delta": 0.0, "normalization_mismatch": False, "feature_reorder_detected": False},
        "engine_replay": {"global_max_probability": 0.379, "all_below_threshold": True},
    }
    base.update(overrides)
    return base


class TestConfig(unittest.TestCase):
    def test_threshold(self):
        self.assertEqual(TREND_THRESHOLD, 0.40)

    def test_observed_ceiling(self):
        self.assertAlmostEqual(OBSERVED_CEILING, 0.379, places=3)

    def test_root_causes(self):
        self.assertIn("COMBINED_CAUSE", VALID_ROOT_CAUSES)

    def test_recommendations(self):
        self.assertIn("RETRAIN_MODEL", VALID_RECOMMENDATIONS)


class TestDistStats(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(dist_stats([])["count"], 0)

    def test_values(self):
        d = dist_stats([0.1, 0.2, 0.3])
        self.assertEqual(d["count"], 3)

    def test_max(self):
        self.assertEqual(dist_stats([0.1, 0.9])["max"], 0.9)


class TestPsi(unittest.TestCase):
    def test_identical_low(self):
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertLess(psi_score(a, a), 0.01)

    def test_different_higher(self):
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([10.0, 11.0, 12.0])
        self.assertGreater(psi_score(a, b), 0.1)


class TestPearson(unittest.TestCase):
    def test_perfect(self):
        x = np.array([1.0, 2.0, 3.0])
        self.assertAlmostEqual(pearson_corr(x, x), 1.0)

    def test_short(self):
        self.assertEqual(pearson_corr(np.array([1.0]), np.array([2.0])), 0.0)


class TestRootCauseDetector(unittest.TestCase):
    def test_returns_valid_cause(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertIn(r["root_cause"], VALID_ROOT_CAUSES)

    def test_evidence_score(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertGreaterEqual(r["evidence_score"], 0.0)

    def test_top_factors(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertGreaterEqual(len(r["top_contributing_factors"]), 1)

    def test_pipeline_corruption(self):
        inp = _root_inputs()
        inp["pipeline_audit"] = {"flags": ["MISSING_FEATURES"], "bundle_vs_filter_max_delta": 0.1, "normalization_mismatch": True, "feature_reorder_detected": True}
        r = detect_trend_ceiling_root_cause(**inp)
        self.assertIn(r["root_cause"], ("PIPELINE_CORRUPTION", "TRAIN_INFERENCE_MISMATCH", "COMBINED_CAUSE"))

    def test_feature_drift(self):
        inp = _root_inputs()
        inp["pipeline_audit"] = {"flags": [], "bundle_vs_filter_max_delta": 0, "normalization_mismatch": False, "feature_reorder_detected": False}
        r = detect_trend_ceiling_root_cause(**inp)
        self.assertIn(r["root_cause"], VALID_ROOT_CAUSES)


class TestRecommendation(unittest.TestCase):
    def test_feature_drift_rec(self):
        r = build_ceiling_recommendation({"root_cause": "FEATURE_DRIFT", "evidence_score": 0.8, "quantitative_proof": {}})
        self.assertEqual(r["recommended_action"], "FIX_FEATURE_PIPELINE")

    def test_no_implement(self):
        r = build_ceiling_recommendation({"root_cause": "MODEL_SATURATION", "quantitative_proof": {}})
        self.assertFalse(r["implements_change"])

    def test_calibration_rec(self):
        r = build_ceiling_recommendation({"root_cause": "PROBABILITY_CALIBRATION_LIMIT", "quantitative_proof": {"live_max_probability": 0.37, "threshold": 0.4}})
        self.assertEqual(r["recommended_action"], "RECALIBRATE_PROBABILITIES")

    def test_combined_rec(self):
        r = build_ceiling_recommendation({
            "root_cause": "COMBINED_CAUSE",
            "quantitative_proof": {"live_max_probability": 0.37, "training_max_probability": 0.8, "threshold": 0.4},
        })
        self.assertEqual(r["recommended_action"], "HYBRID_MODEL_ENSEMBLE")


class TestValidator(unittest.TestCase):
    def test_pass(self):
        c = _ceiling()
        c["per_feature"] = []
        v = validate_phase15k(
            ceiling=c,
            root_cause={
                "root_cause": "PROBABILITY_CALIBRATION_LIMIT",
                "evidence_score": 0.9,
                "top_contributing_factors": ["x"],
                "quantitative_proof": {"live_max_probability": 0.379},
            },
            recommendation={"recommended_action": "RECALIBRATE_PROBABILITIES"},
            pipeline_audit={"feature_order_identical": True},
            engine_replay={"all_below_threshold": True},
        )
        self.assertTrue(v["all_passed"])

    def test_fail_no_factors(self):
        v = validate_phase15k(
            ceiling=_ceiling(),
            root_cause={"root_cause": "X", "evidence_score": 0.5, "top_contributing_factors": []},
            recommendation={},
            pipeline_audit={},
            engine_replay={},
        )
        self.assertFalse(v["all_passed"])


class TestReportGenerator(unittest.TestCase):
    def test_writes_nine_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15k_reports(
                trend_ceiling_analysis={}, feature_ceiling_impact={},
                distribution_drift_ceiling={}, model_behavior_simulation={},
                pipeline_injection_audit={}, engine_replay_trace={},
                root_cause={}, recommendation={}, final_report={"status": "PASS"},
                base_dir=tmp,
            )
            self.assertEqual(len(list(out.glob("*.json"))), 9)


class TestModuleImports(unittest.TestCase):
    def test_ceiling_analyzer(self):
        from tradingbot.ml.research.phase15k.ceiling_analyzer import analyze_trend_ceiling
        self.assertTrue(callable(analyze_trend_ceiling))

    def test_feature_impact(self):
        from tradingbot.ml.research.phase15k.feature_ceiling_impact import analyze_feature_ceiling_impact
        self.assertTrue(callable(analyze_feature_ceiling_impact))

    def test_distribution_drift(self):
        from tradingbot.ml.research.phase15k.distribution_drift_ceiling import analyze_distribution_drift_ceiling
        self.assertTrue(callable(analyze_distribution_drift_ceiling))

    def test_model_behavior(self):
        from tradingbot.ml.research.phase15k.model_behavior_simulator import simulate_model_behavior
        self.assertTrue(callable(simulate_model_behavior))

    def test_pipeline_audit(self):
        from tradingbot.ml.research.phase15k.pipeline_injection_audit import audit_pipeline_injection
        self.assertTrue(callable(audit_pipeline_injection))

    def test_engine_replay(self):
        from tradingbot.ml.research.phase15k.engine_replay_trace import replay_engine_trace
        self.assertTrue(callable(replay_engine_trace))

    def test_orchestrator(self):
        from tradingbot.ml.research.phase15k.orchestrator import run_phase15k_ceiling_analysis
        self.assertTrue(callable(run_phase15k_ceiling_analysis))


class TestPackageLayout(unittest.TestCase):
    def test_modules(self):
        names = [
            "ceiling_analyzer.py", "feature_ceiling_impact.py", "distribution_drift_ceiling.py",
            "model_behavior_simulator.py", "pipeline_injection_audit.py", "engine_replay_trace.py",
            "trend_ceiling_root_cause.py", "recommendation_ceiling.py", "orchestrator.py",
            "report_generator.py", "validator.py", "config.py", "data_access.py",
        ]
        for n in names:
            self.assertTrue((PKG / n).is_file(), n)

    def test_cli(self):
        self.assertTrue((ROOT / "scripts" / "run_phase15k_ceiling_analysis.py").is_file())


class TestSyntax(unittest.TestCase):
    def test_syntax(self):
        for py in PKG.glob("*.py"):
            ast.parse(py.read_text(encoding="utf-8"))


class TestOrchestratorMocked(unittest.TestCase):
    def test_mocked_pass(self):
        from tradingbot.ml.research.phase15k.orchestrator import run_phase15k_ceiling_analysis
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tradingbot.ml.research.phase15k.orchestrator.CandleStore") as cs:
                cs.return_value.load.return_value = pd.DataFrame(
                    {"close": [1.0]}, index=pd.DatetimeIndex(["2025-01-01"], tz="UTC"),
                )
                with mock.patch("tradingbot.ml.research.phase15k.orchestrator.DatasetStore") as ds:
                    ds.return_value.load_v2.return_value = pd.DataFrame({"timestamp": ["2025-01-01"], "f": [1.0]})
                    with mock.patch("tradingbot.ml.research.phase15k.orchestrator.analyze_trend_ceiling", return_value=_ceiling()):
                        with mock.patch("tradingbot.ml.research.phase15k.orchestrator.analyze_feature_ceiling_impact", return_value={"ceiling_breaking_features": []}):
                            with mock.patch("tradingbot.ml.research.phase15k.orchestrator.analyze_distribution_drift_ceiling", return_value={"per_feature": [], "drift_critical_features": []}):
                                with mock.patch("tradingbot.ml.research.phase15k.orchestrator.simulate_model_behavior", return_value={"flags": []}):
                                    with mock.patch("tradingbot.ml.research.phase15k.orchestrator.audit_pipeline_injection", return_value={"feature_order_identical": True, "flags": []}):
                                        with mock.patch("tradingbot.ml.research.phase15k.orchestrator.replay_engine_trace", return_value={"all_below_threshold": True, "global_max_probability": 0.379}):
                                            with mock.patch("tradingbot.ml.research.phase15k.orchestrator.detect_trend_ceiling_root_cause", return_value={
                                                "root_cause": "PROBABILITY_CALIBRATION_LIMIT",
                                                "evidence_score": 0.9,
                                                "top_contributing_factors": ["ceiling"],
                                                "quantitative_proof": {"live_max_probability": 0.379},
                                            }):
                                                with mock.patch("tradingbot.ml.research.phase15k.orchestrator.Phase15KContext") as pctx:
                                                    pctx.build.return_value = mock.Mock(bundle=mock.Mock(), live_rows=[], train_samples=pd.DataFrame())
                                                    with mock.patch("tradingbot.ml.research.phase15k.orchestrator.build_ceiling_recommendation", return_value={"recommended_action": "RECALIBRATE_PROBABILITIES"}):
                                                        r = run_phase15k_ceiling_analysis(base_dir=tmp, days=30)
        self.assertEqual(r.status, "PASS")


class TestPsiCritical(unittest.TestCase):
    def test_value(self):
        self.assertEqual(PSI_CRITICAL, 0.25)


class TestReportsDir(unittest.TestCase):
    def test_suffix(self):
        from tradingbot.ml.research.phase15k.config import reports_dir
        self.assertTrue(str(reports_dir()).endswith("phase15k"))


class TestRootCauseProof(unittest.TestCase):
    def test_quantitative_proof_keys(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertIn("live_max_probability", r["quantitative_proof"])


class TestRecommendationRationale(unittest.TestCase):
    def test_has_rationale(self):
        r = build_ceiling_recommendation({
            "root_cause": "PROBABILITY_CALIBRATION_LIMIT",
            "evidence_score": 0.7,
            "quantitative_proof": {"live_max_probability": 0.37, "threshold": 0.4},
        })
        self.assertIn("rationale", r)


class TestValidatorReadOnly(unittest.TestCase):
    def test_no_retrain_flag(self):
        v = validate_phase15k(
            ceiling=_ceiling(), root_cause={"root_cause": "X", "evidence_score": 1, "top_contributing_factors": ["a"]},
            recommendation={"recommended_action": "X"}, pipeline_audit={"feature_order_identical": True},
            engine_replay={"all_below_threshold": True},
        )
        self.assertTrue(v["checks"]["no_retraining"])


class TestDistStatsPercentiles(unittest.TestCase):
    def test_p99(self):
        vals = list(np.linspace(0, 1, 100))
        self.assertGreater(dist_stats(vals)["p99"], 0.9)


class TestRootCauseCombined(unittest.TestCase):
    def test_combined_possible(self):
        inp = _root_inputs()
        inp["distribution_drift"]["drift_critical_features"] = ["a", "b", "c", "d"]
        inp["model_behavior"]["tree_saturation"] = True
        inp["pipeline_audit"]["normalization_mismatch"] = True
        inp["pipeline_audit"]["bundle_vs_filter_max_delta"] = 0.05
        r = detect_trend_ceiling_root_cause(**inp)
        self.assertIn(r["root_cause"], VALID_ROOT_CAUSES)


class TestFinalReportFile(unittest.TestCase):
    def test_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15k_reports(
                trend_ceiling_analysis={}, feature_ceiling_impact={},
                distribution_drift_ceiling={}, model_behavior_simulation={},
                pipeline_injection_audit={}, engine_replay_trace={},
                root_cause={}, recommendation={}, final_report={"status": "PASS"},
                base_dir=tmp,
            )
            self.assertTrue((out / "phase15k_final_report.json").exists())


class TestGapToThreshold(unittest.TestCase):
    def test_gap_positive(self):
        c = _ceiling(0.379, 0.85)
        self.assertGreater(c["mathematical_bound"]["gap_to_threshold"], 0)


class TestRecommendationRetrain(unittest.TestCase):
    def test_model_saturation(self):
        r = build_ceiling_recommendation({"root_cause": "MODEL_SATURATION", "quantitative_proof": {}})
        self.assertEqual(r["recommended_action"], "RETRAIN_MODEL")


class TestRecommendationFreeze(unittest.TestCase):
    def test_unknown_maps(self):
        r = build_ceiling_recommendation({"root_cause": "PROBABILITY_CALIBRATION_LIMIT", "quantitative_proof": {}})
        self.assertIn(r["recommended_action"], VALID_RECOMMENDATIONS)


class TestValidatorLiveMax(unittest.TestCase):
    def test_live_max_recorded(self):
        v = validate_phase15k(
            ceiling=_ceiling(0.379), root_cause={"root_cause": "X", "evidence_score": 1, "top_contributing_factors": ["a"]},
            recommendation={"recommended_action": "RECALIBRATE_PROBABILITIES"},
            pipeline_audit={"feature_order_identical": True}, engine_replay={"all_below_threshold": True},
        )
        self.assertAlmostEqual(v["live_max_probability"], 0.379)


class TestHypothesisList(unittest.TestCase):
    def test_ten_hypotheses(self):
        from tradingbot.ml.research.phase15k.config import HYPOTHESES
        self.assertEqual(len(HYPOTHESES), 10)


class TestRootCauseScores(unittest.TestCase):
    def test_hypothesis_scores(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertIsInstance(r["hypothesis_scores"], dict)


class TestRecommendationAlternatives(unittest.TestCase):
    def test_alternatives(self):
        r = build_ceiling_recommendation({"root_cause": "FEATURE_DRIFT", "quantitative_proof": {}})
        self.assertGreater(len(r["alternatives_considered"]), 0)


class TestValidatorThreshold(unittest.TestCase):
    def test_no_threshold_changes(self):
        v = validate_phase15k(
            ceiling=_ceiling(), root_cause={"root_cause": "X", "evidence_score": 1, "top_contributing_factors": ["a"]},
            recommendation={"recommended_action": "X"}, pipeline_audit={"feature_order_identical": True},
            engine_replay={"all_below_threshold": True},
        )
        self.assertTrue(v["checks"]["no_threshold_changes"])


class TestReportRootCauseJson(unittest.TestCase):
    def test_root_cause_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15k_reports(
                trend_ceiling_analysis={}, feature_ceiling_impact={},
                distribution_drift_ceiling={}, model_behavior_simulation={},
                pipeline_injection_audit={}, engine_replay_trace={},
                root_cause={"root_cause": "PROBABILITY_CALIBRATION_LIMIT"}, recommendation={},
                final_report={}, base_dir=tmp,
            )
            data = json.loads((out / "root_cause.json").read_text(encoding="utf-8"))
            self.assertEqual(data["root_cause"], "PROBABILITY_CALIBRATION_LIMIT")


class TestLabelShiftCause(unittest.TestCase):
    def test_label_shift_detected(self):
        inp = _root_inputs()
        inp["ceiling"] = _ceiling(0.35, 0.90)
        inp["ceiling"]["probability_shift_train_vs_live"] = {"max_delta": 0.55}
        inp["pipeline_audit"] = {"flags": [], "bundle_vs_filter_max_delta": 0, "normalization_mismatch": False, "feature_reorder_detected": False}
        inp["distribution_drift"] = {"drift_critical_features": [], "per_feature": []}
        r = detect_trend_ceiling_root_cause(**inp)
        self.assertIn("LABEL_SHIFT", r["hypothesis_scores"])


class TestTrainInferenceMismatch(unittest.TestCase):
    def test_mismatch_cause(self):
        inp = _root_inputs()
        inp["pipeline_audit"] = {
            "flags": ["NORMALIZATION_MISMATCH"],
            "bundle_vs_filter_max_delta": 0.01,
            "normalization_mismatch": True,
            "feature_reorder_detected": True,
        }
        r = detect_trend_ceiling_root_cause(**inp)
        self.assertIn(r["root_cause"], ("TRAIN_INFERENCE_MISMATCH", "PIPELINE_CORRUPTION", "COMBINED_CAUSE"))


class TestValidatorProduction(unittest.TestCase):
    def test_no_production_mod(self):
        v = validate_phase15k(
            ceiling=_ceiling(), root_cause={"root_cause": "X", "evidence_score": 1, "top_contributing_factors": ["a"]},
            recommendation={"recommended_action": "X"}, pipeline_audit={"feature_order_identical": True},
            engine_replay={"all_below_threshold": True},
        )
        self.assertTrue(v["checks"]["no_production_modifications"])


class TestPearsonZeroStd(unittest.TestCase):
    def test_constant(self):
        self.assertEqual(pearson_corr(np.ones(5), np.arange(5)), 0.0)


class TestPsiShort(unittest.TestCase):
    def test_short_arrays(self):
        self.assertEqual(psi_score(np.array([1.0]), np.array([2.0])), 0.0)


class TestDistStatsSingle(unittest.TestCase):
    def test_single(self):
        d = dist_stats([0.5])
        self.assertEqual(d["min"], d["max"])


class TestRecommendationPipelineFix(unittest.TestCase):
    def test_pipeline_corruption(self):
        r = build_ceiling_recommendation({"root_cause": "PIPELINE_CORRUPTION", "quantitative_proof": {}})
        self.assertEqual(r["recommended_action"], "FIX_FEATURE_PIPELINE")


class TestValidatorEngineCollapse(unittest.TestCase):
    def test_quantified(self):
        v = validate_phase15k(
            ceiling=_ceiling(), root_cause={"root_cause": "X", "evidence_score": 1, "top_contributing_factors": ["a"]},
            recommendation={"recommended_action": "X"}, pipeline_audit={"feature_order_identical": True},
            engine_replay={"all_below_threshold": True},
        )
        self.assertTrue(v["checks"]["engine_collapse_quantified"])


class TestRootCauseCandidates(unittest.TestCase):
    def test_has_candidates(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertGreater(len(r["candidates"]), 0)


class TestReportCeilingFile(unittest.TestCase):
    def test_ceiling_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15k_reports(
                trend_ceiling_analysis={"phase": "15K"}, feature_ceiling_impact={},
                distribution_drift_ceiling={}, model_behavior_simulation={},
                pipeline_injection_audit={}, engine_replay_trace={},
                root_cause={}, recommendation={}, final_report={}, base_dir=tmp,
            )
            self.assertTrue((out / "trend_ceiling_analysis.json").exists())


class TestConfigDefaults(unittest.TestCase):
    def test_symbol(self):
        from tradingbot.ml.research.phase15k.config import DEFAULT_SYMBOL
        self.assertEqual(DEFAULT_SYMBOL, "XAUUSD")

    def test_timeframe(self):
        from tradingbot.ml.research.phase15k.config import DEFAULT_TIMEFRAME
        self.assertEqual(DEFAULT_TIMEFRAME, "M5")

    def test_days(self):
        from tradingbot.ml.research.phase15k.config import DEFAULT_DAYS
        self.assertEqual(DEFAULT_DAYS, 365)

    def test_seed(self):
        from tradingbot.ml.research.phase15k.config import DEFAULT_SEED
        self.assertEqual(DEFAULT_SEED, 42)

    def test_stride(self):
        from tradingbot.ml.research.phase15k.config import DEFAULT_STRIDE
        self.assertEqual(DEFAULT_STRIDE, 15)


class TestDistStatsMedian(unittest.TestCase):
    def test_median(self):
        self.assertEqual(dist_stats([1.0, 2.0, 3.0])["median"], 2.0)

    def test_std(self):
        self.assertGreater(dist_stats([1.0, 2.0, 3.0, 4.0])["std"], 0)


class TestPearsonNegative(unittest.TestCase):
    def test_negative(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        y = np.array([4.0, 3.0, 2.0, 1.0])
        self.assertLess(pearson_corr(x, y), -0.9)


class TestRootCauseCalibration(unittest.TestCase):
    def test_calibration_wins(self):
        inp = _root_inputs()
        inp["ceiling"] = _ceiling(0.379, 0.42)
        inp["ceiling"]["probability_shift_train_vs_live"] = {"max_delta": 0.04}
        inp["pipeline_audit"] = {"flags": [], "bundle_vs_filter_max_delta": 0, "normalization_mismatch": False, "feature_reorder_detected": False}
        inp["distribution_drift"] = {"drift_critical_features": [], "per_feature": []}
        inp["feature_impact"] = {"ceiling_breaking_features": []}
        inp["model_behavior"] = {"flags": [], "tree_saturation": False, "path_collapse": False, "low_variance_leaves": False}
        r = detect_trend_ceiling_root_cause(**inp)
        self.assertEqual(r["root_cause"], "PROBABILITY_CALIBRATION_LIMIT")


class TestRecommendationLabelShift(unittest.TestCase):
    def test_label_shift(self):
        r = build_ceiling_recommendation({"root_cause": "LABEL_SHIFT", "quantitative_proof": {}})
        self.assertEqual(r["recommended_action"], "RETRAIN_MODEL")


class TestRecommendationTrainMismatch(unittest.TestCase):
    def test_train_inference(self):
        r = build_ceiling_recommendation({"root_cause": "TRAIN_INFERENCE_MISMATCH", "quantitative_proof": {}})
        self.assertEqual(r["recommended_action"], "FIX_FEATURE_PIPELINE")


class TestValidatorFailedList(unittest.TestCase):
    def test_failed_nonempty(self):
        v = validate_phase15k(
            ceiling={"live_trend_distribution": {"max": 0}},
            root_cause={"root_cause": "X", "evidence_score": 0.5, "top_contributing_factors": []},
            recommendation={},
            pipeline_audit={},
            engine_replay={},
        )
        self.assertGreater(len(v["failed"]), 0)


class TestReportAllFiles(unittest.TestCase):
    def test_all_names(self):
        names = [
            "trend_ceiling_analysis.json", "feature_ceiling_impact.json",
            "distribution_drift_ceiling.json", "model_behavior_simulation.json",
            "pipeline_injection_audit.json", "engine_replay_trace.json",
            "root_cause.json", "recommendation.json", "phase15k_final_report.json",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15k_reports(
                trend_ceiling_analysis={}, feature_ceiling_impact={},
                distribution_drift_ceiling={}, model_behavior_simulation={},
                pipeline_injection_audit={}, engine_replay_trace={},
                root_cause={}, recommendation={}, final_report={}, base_dir=tmp,
            )
            for n in names:
                self.assertTrue((out / n).is_file(), n)


class TestPhase15KResult(unittest.TestCase):
    def test_to_dict(self):
        from tradingbot.ml.research.phase15k.orchestrator import Phase15KResult
        r = Phase15KResult("PASS", "X", 0.9, "Y", "/tmp")
        d = r.to_dict()
        self.assertEqual(d["phase"], "15K")


class TestDriftCeilingCorr(unittest.TestCase):
    def test_constant(self):
        from tradingbot.ml.research.phase15k.config import DRIFT_CEILING_CORR
        self.assertEqual(DRIFT_CEILING_CORR, 0.5)


class TestRootCauseEvidence(unittest.TestCase):
    def test_engine_replay_in_proof(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertIn("engine_replay_global_max", r["quantitative_proof"])


class TestRecommendationImplementsFalse(unittest.TestCase):
    def test_all_false(self):
        for cause in VALID_ROOT_CAUSES:
            r = build_ceiling_recommendation({"root_cause": cause, "quantitative_proof": {}})
            self.assertFalse(r["implements_change"])


class TestValidatorChecksKeys(unittest.TestCase):
    def test_all_check_keys(self):
        v = validate_phase15k(
            ceiling=_ceiling(), root_cause={"root_cause": "X", "evidence_score": 1, "top_contributing_factors": ["a"]},
            recommendation={"recommended_action": "X"}, pipeline_audit={"feature_order_identical": True},
            engine_replay={"all_below_threshold": True},
        )
        self.assertIn("no_retraining", v["checks"])


class TestPsiBins(unittest.TestCase):
    def test_many_bins(self):
        a = np.random.default_rng(42).normal(0, 1, 500)
        b = np.random.default_rng(43).normal(2, 1, 500)
        self.assertGreater(psi_score(a, b, bins=20), 0.1)


class TestDistStatsP95(unittest.TestCase):
    def test_p95(self):
        vals = list(range(100))
        self.assertGreaterEqual(dist_stats(vals)["p95"], 94)


class TestRootCausePhase(unittest.TestCase):
    def test_phase_field(self):
        r = detect_trend_ceiling_root_cause(**_root_inputs())
        self.assertEqual(r["phase"], "15K")


class TestRecommendationPhase(unittest.TestCase):
    def test_phase_field(self):
        r = build_ceiling_recommendation({"root_cause": "FEATURE_DRIFT", "quantitative_proof": {}})
        self.assertEqual(r["phase"], "15K")


class TestValidatorRootCauseField(unittest.TestCase):
    def test_root_cause_echo(self):
        v = validate_phase15k(
            ceiling=_ceiling(), root_cause={"root_cause": "MODEL_SATURATION", "evidence_score": 1, "top_contributing_factors": ["a"]},
            recommendation={"recommended_action": "RETRAIN_MODEL"}, pipeline_audit={"feature_order_identical": True},
            engine_replay={"all_below_threshold": True},
        )
        self.assertEqual(v["root_cause"], "MODEL_SATURATION")


class TestCliExists(unittest.TestCase):
    def test_cli_syntax(self):
        cli = ROOT / "scripts" / "run_phase15k_ceiling_analysis.py"
        ast.parse(cli.read_text(encoding="utf-8"))


class TestHypothesisH1(unittest.TestCase):
    def test_h1_name(self):
        from tradingbot.ml.research.phase15k.config import HYPOTHESES
        self.assertTrue(any("H1" in h for h in HYPOTHESES))


class TestHypothesisH10(unittest.TestCase):
    def test_h10_name(self):
        from tradingbot.ml.research.phase15k.config import HYPOTHESES
        self.assertTrue(any("H10" in h for h in HYPOTHESES))


if __name__ == "__main__":
    unittest.main()
