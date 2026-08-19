"""Phase 15G — frozen bundle confidence analysis tests."""

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

from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
from tradingbot.ml.research.phase15g.bundle_statistics import (
    compare_distributions,
    distribution_stats,
    histogram,
)
from tradingbot.ml.research.phase15g.confidence_recovery import build_recovery_recommendation
from tradingbot.ml.research.phase15g.config import (
    RESEARCH_CALIB_THRESHOLD,
    RISK_GATE_THRESHOLD,
    SIMULATION_THRESHOLDS,
    reports_dir,
)
from tradingbot.ml.research.phase15g.report_generator import write_phase15g_reports
from tradingbot.ml.research.phase15g.validator import validate_phase15g_results
from tradingbot.ml.risk_intelligence.risk_policy import MIN_CONFIDENCE_FOR_RISK

PHASE15G_PKG = ROOT / "tradingbot" / "ml" / "research" / "phase15g"


class TestConfig(unittest.TestCase):
    def test_research_threshold(self):
        self.assertEqual(RESEARCH_CALIB_THRESHOLD, 0.30)

    def test_risk_gate(self):
        self.assertEqual(RISK_GATE_THRESHOLD, 0.55)

    def test_simulation_thresholds(self):
        self.assertEqual(len(SIMULATION_THRESHOLDS), 4)

    def test_reports_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("phase15g", str(reports_dir(tmp)))


class TestBundleStatistics(unittest.TestCase):
    def test_distribution_empty(self):
        d = distribution_stats([])
        self.assertEqual(d["count"], 0)

    def test_distribution_values(self):
        d = distribution_stats([0.1, 0.5, 0.9])
        self.assertEqual(d["count"], 3)
        self.assertAlmostEqual(d["mean"], 0.5, places=4)

    def test_histogram(self):
        h = histogram([0.1, 0.2, 0.8, 0.9])
        self.assertIn("counts", h)

    def test_histogram_single(self):
        h = histogram([0.5, 0.5])
        self.assertEqual(sum(h["counts"]), 2)

    def test_compare_distributions(self):
        c = compare_distributions([0.3, 0.4], [0.7, 0.8])
        self.assertIn("mean_diff", c)


class TestValidator(unittest.TestCase):
    def _payloads(self):
        bundle = {"trend_bars_evaluated": 10}
        platt = {"synthetic_curve": [{"raw_input": 0.1, "calibrated": 0.2}]}
        ceiling = {"maximum_calibrated_confidence": 0.49}
        research_vs = {"bars_compared": 100}
        equivalence = {"synthetic_equivalence": {"research_threshold": 0.3}}
        recovery = {
            "why_frozen_never_reaches_riskgate": "test",
            "no_production_changes": True,
        }
        return bundle, platt, ceiling, research_vs, equivalence, recovery

    def test_all_pass(self):
        b, p, c, r, e, rec = self._payloads()
        v = validate_phase15g_results(
            bundle_audit=b, platt=p, ceiling=c,
            research_vs=r, equivalence=e, recovery=rec,
        )
        self.assertTrue(v["all_passed"])

    def test_fail_missing_ceiling(self):
        b, p, _, r, e, rec = self._payloads()
        v = validate_phase15g_results(
            bundle_audit=b, platt=p, ceiling={},
            research_vs=r, equivalence=e, recovery=rec,
        )
        self.assertFalse(v["all_passed"])


class TestRecoveryRecommendation(unittest.TestCase):
    def test_recommendation_only(self):
        rec = build_recovery_recommendation(
            ceiling={"maximum_calibrated_confidence": 0.49, "ceiling_below_risk_gate": True,
                     "risk_gate_requirement": 0.55},
            bundle_audit={"frozen_outputs_compressed": True, "comparison": {"mean_diff": 0.1}},
            research_vs={"primary_difference_source": "trend_engine_model_mismatch"},
            platt={"maximum_attainable_confidence": {"combined_max": 0.497}},
            equivalence={"empirical_frozen_threshold_when_research_passes": 0.49},
            risk_sim={"first_accepting_threshold": 0.45},
            production_replay={"calibration_actionable": 100, "risk_quality_pass": 0},
        )
        self.assertTrue(rec["recommendation_only"])
        self.assertIn("outcome", rec["single_recommendation"])

    def test_why_blocked(self):
        rec = build_recovery_recommendation(
            ceiling={"maximum_calibrated_confidence": 0.49, "ceiling_below_risk_gate": True,
                     "risk_gate_requirement": 0.55},
            bundle_audit={"frozen_outputs_compressed": False, "comparison": {"mean_diff": 0.0}},
            research_vs={"primary_difference_source": "platt"},
            platt={"maximum_attainable_confidence": {"combined_max": 0.49}},
            equivalence={},
            risk_sim={},
            production_replay={"calibration_actionable": 0, "risk_quality_pass": 0},
        )
        self.assertIn("0.49", rec["why_frozen_never_reaches_riskgate"])


class TestReportGenerator(unittest.TestCase):
    def test_writes_eight_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15g_reports(
                bundle_probability={}, platt_curve={}, confidence_ceiling={},
                riskgate_simulation={}, research_vs_bundle={},
                threshold_equivalence={}, recovery_recommendation={},
                final_report={"status": "PASS"},
                base_dir=tmp,
            )
            self.assertEqual(len(list(out.glob("*.json"))), 8)

    def test_final_report_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15g_reports(
                bundle_probability={}, platt_curve={}, confidence_ceiling={},
                riskgate_simulation={}, research_vs_bundle={},
                threshold_equivalence={}, recovery_recommendation={},
                final_report={"recommendation": "READY_FOR_PHASE15H"},
                base_dir=tmp,
            )
            data = json.loads((out / "phase15g_final_report.json").read_text())
            self.assertEqual(data["recommendation"], "READY_FOR_PHASE15H")


class TestSafetyGuards(unittest.TestCase):
    def test_no_kernel_import_in_orchestrator(self):
        src = (PHASE15G_PKG / "orchestrator.py").read_text(encoding="utf-8")
        self.assertNotIn("TradingKernel", src)

    def test_no_riskgate_modification(self):
        for name in PHASE15G_PKG.glob("*.py"):
            src = name.read_text(encoding="utf-8")
            self.assertNotIn("class RiskGate", src)

    def test_recovery_no_implementation(self):
        src = (PHASE15G_PKG / "confidence_recovery.py").read_text(encoding="utf-8")
        self.assertIn("none_in_15g", src)

    def test_risk_sim_marked_simulation(self):
        src = (PHASE15G_PKG / "risk_gate_simulator.py").read_text(encoding="utf-8")
        self.assertIn("simulation_only", src)


class TestPackageStructure(unittest.TestCase):
    def test_modules_exist(self):
        expected = [
            "bundle_probability_audit.py", "platt_curve_analysis.py",
            "confidence_ceiling.py", "risk_gate_simulator.py",
            "confidence_recovery.py", "threshold_equivalence.py",
            "research_vs_bundle.py", "bundle_statistics.py",
            "production_replay.py", "orchestrator.py",
            "report_generator.py", "validator.py", "config.py",
        ]
        for name in expected:
            self.assertTrue((PHASE15G_PKG / name).is_file(), name)

    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase15g_confidence_analysis.py").is_file())


class TestRiskPolicyConstants(unittest.TestCase):
    def test_min_confidence_matches_config(self):
        self.assertEqual(MIN_CONFIDENCE_FOR_RISK, RISK_GATE_THRESHOLD)


class TestPlattCurveSynthetic(unittest.TestCase):
    def test_synthetic_raw(self):
        from tradingbot.ml.research.phase15g.platt_curve_analysis import _synthetic_raw
        r = _synthetic_raw(0.5)
        self.assertEqual(r.engine_signal, "SELL")


class TestThresholdEquivalence(unittest.TestCase):
    def test_find_equivalent_structure(self):
        from tradingbot.ml.research.phase15g.threshold_equivalence import _find_frozen_equivalent

        class _MockMethod:
            def calibrate(self, raw):
                from tradingbot.ml.confidence_engine.calibration_types import CalibratedConfidence
                return CalibratedConfidence(
                    calibrated_value=raw.raw_value * 0.8,
                    adjustment_factor=0.8,
                    confidence_band="mid",
                    explanation=[], trace=[], adjustments=[],
                    raw_value=raw.raw_value, engine=raw.engine, regime=raw.regime,
                )

        m = _MockMethod()
        result = _find_frozen_equivalent(m, m, target=0.30)
        self.assertIn("frozen_calibrated_equivalent", result)


class TestBundleAuditMocked(unittest.TestCase):
    def test_audit_structure(self):
        from tradingbot.ml.research.phase15g.bundle_probability_audit import audit_bundle_probabilities

        idx = pd.date_range("2025-01-01", periods=50, freq="5min", tz="UTC")
        candles = pd.DataFrame({"close": np.linspace(1900, 2000, 50)}, index=idx)
        dataset = pd.DataFrame({"timestamp": idx, "feature_a": np.random.rand(50)})

        with mock.patch(
            "tradingbot.ml.research.phase15g.bundle_probability_audit.build_unified_frame"
        ) as bu:
            bu.return_value = pd.DataFrame({
                "timestamp": idx,
                "regime": ["TREND"] * 50,
                "close": np.linspace(1900, 2000, 50),
            })
            with mock.patch(
                "tradingbot.ml.research.phase15g.bundle_probability_audit.build_market_context"
            ) as bmc:
                from tradingbot.ml.decision_engine.decision_types import EngineSignal

                def _ctx(*a, **kw):
                    from tradingbot.ml.decision_engine.decision_types import MarketContext
                    is_frozen = kw.get("trend_engine") is not None
                    prob = 0.35 if "frozen" in str(type(kw.get("trend_engine"))) else 0.45
                    return MarketContext(
                        symbol="XAUUSD", timeframe="M5", features={},
                        regime="TREND", regime_strength=0.8,
                        range_signal=EngineSignal("HOLD", 0.0, "phase9_9", 0.0, {}),
                        trend_signal=EngineSignal("SELL", 0.5, "trend_rf_v40", prob, {}),
                        volatility=50.0, session="london",
                    )

                bmc.side_effect = _ctx
                with mock.patch(
                    "tradingbot.ml.research.phase15g.bundle_probability_audit._frozen_trend_engines"
                ) as fe:
                    fe.return_value = (mock.Mock(), mock.Mock(name="frozen"))
                    with mock.patch(
                        "tradingbot.ml.research.phase15g.bundle_probability_audit.load_production_engines"
                    ) as lpe:
                        lpe.return_value = (mock.Mock(), mock.Mock(name="research"))
                        result = audit_bundle_probabilities(candles, dataset, stride=10, days=30)
        self.assertIn("frozen_bundle", result)


class TestOrchestratorMocked(unittest.TestCase):
    def test_run_returns_result(self):
        from tradingbot.ml.research.phase15g.orchestrator import run_phase15g_analysis

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tradingbot.ml.research.phase15g.orchestrator.CandleStore") as cs:
                cs.return_value.load.return_value = pd.DataFrame(
                    {"close": [1.0]}, index=pd.DatetimeIndex(["2025-01-01"], tz="UTC"),
                )
                with mock.patch("tradingbot.ml.research.phase15g.orchestrator.DatasetStore") as ds:
                    ds.return_value.load_v2.return_value = pd.DataFrame(
                        {"timestamp": ["2025-01-01"], "f": [1.0]},
                    )
                    with mock.patch(
                        "tradingbot.ml.research.phase15g.orchestrator.audit_bundle_probabilities",
                        return_value={"trend_bars_evaluated": 10, "frozen_outputs_compressed": True,
                                      "comparison": {"mean_diff": 0.1}},
                    ):
                        with mock.patch(
                            "tradingbot.ml.research.phase15g.orchestrator.analyze_platt_curve",
                            return_value={"synthetic_curve": [{}], "maximum_attainable_confidence": {"combined_max": 0.49}},
                        ):
                            with mock.patch(
                                "tradingbot.ml.research.phase15g.orchestrator.measure_confidence_ceiling",
                                return_value={"maximum_calibrated_confidence": 0.49,
                                              "ceiling_below_risk_gate": True, "risk_gate_requirement": 0.55},
                            ):
                                with mock.patch(
                                    "tradingbot.ml.research.phase15g.orchestrator.simulate_risk_gate_thresholds",
                                    return_value={"first_accepting_threshold": 0.45, "results": []},
                                ):
                                    with mock.patch(
                                        "tradingbot.ml.research.phase15g.orchestrator.compare_research_vs_frozen",
                                        return_value={"bars_compared": 50,
                                                      "primary_difference_source": "trend_engine_model_mismatch",
                                                      "research_accepted_at_cal_threshold": 10,
                                                      "frozen_accepted_at_cal_threshold": 0},
                                    ):
                                        with mock.patch(
                                            "tradingbot.ml.research.phase15g.orchestrator.compute_threshold_equivalence",
                                            return_value={"synthetic_equivalence": {"research_threshold": 0.3},
                                                          "empirical_frozen_threshold_when_research_passes": 0.49},
                                        ):
                                            with mock.patch(
                                                "tradingbot.ml.research.phase15g.orchestrator.replay_production_pipeline",
                                                return_value={"calibration_actionable": 100, "risk_quality_pass": 0},
                                            ):
                                                result = run_phase15g_analysis(base_dir=tmp, days=30)
        self.assertEqual(result.recommendation, "READY_FOR_PHASE15H")


class TestAstParse(unittest.TestCase):
    def test_all_modules_parse(self):
        for path in PHASE15G_PKG.glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"))


class TestConfidenceCeilingLogic(unittest.TestCase):
    def test_ceiling_proof_format(self):
        from tradingbot.ml.research.phase15g.confidence_ceiling import measure_confidence_ceiling

        self.assertTrue(callable(measure_confidence_ceiling))


class TestProductionReplay(unittest.TestCase):
    def test_replay_callable(self):
        from tradingbot.ml.research.phase15g.production_replay import replay_production_pipeline
        self.assertTrue(callable(replay_production_pipeline))


class TestResearchVsBundle(unittest.TestCase):
    def test_compare_callable(self):
        from tradingbot.ml.research.phase15g.research_vs_bundle import compare_research_vs_frozen
        self.assertTrue(callable(compare_research_vs_frozen))


class TestRiskSimulator(unittest.TestCase):
    def test_simulate_callable(self):
        from tradingbot.ml.research.phase15g.risk_gate_simulator import simulate_risk_gate_thresholds
        self.assertTrue(callable(simulate_risk_gate_thresholds))


class TestInitExports(unittest.TestCase):
    def test_exports(self):
        from tradingbot.ml.research import phase15g
        self.assertTrue(hasattr(phase15g, "run_phase15g_analysis"))

    def test_config_exports(self):
        from tradingbot.ml.research.phase15g import DEFAULT_DAYS, DEFAULT_SEED
        self.assertEqual(DEFAULT_DAYS, 180)
        self.assertEqual(DEFAULT_SEED, 42)


class TestDistributionEdgeCases(unittest.TestCase):
    def test_percentiles_ordered(self):
        vals = list(np.linspace(0, 1, 100))
        d = distribution_stats(vals)
        self.assertLessEqual(d["p10"], d["p50"])
        self.assertLessEqual(d["p50"], d["p90"])

    def test_compare_compressed_flag(self):
        c = compare_distributions([0.1, 0.2], [0.8, 0.9])
        self.assertTrue(c["frozen_compressed_vs_research"])


class TestRecoveryOutcomes(unittest.TestCase):
    def test_outcome_d_platt_mismatch(self):
        rec = build_recovery_recommendation(
            ceiling={"maximum_calibrated_confidence": 0.49, "ceiling_below_risk_gate": True,
                     "risk_gate_requirement": 0.55},
            bundle_audit={"frozen_outputs_compressed": True,
                          "comparison": {"mean_diff": 0.15}},
            research_vs={"primary_difference_source": "trend_engine_model_mismatch"},
            platt={"maximum_attainable_confidence": {"combined_max": 0.497}},
            equivalence={},
            risk_sim={},
            production_replay={"calibration_actionable": 50, "risk_quality_pass": 0},
        )
        self.assertEqual(rec["single_recommendation"]["outcome"], "D")

    def test_mathematical_summary(self):
        rec = build_recovery_recommendation(
            ceiling={"maximum_calibrated_confidence": 0.497, "ceiling_below_risk_gate": True,
                     "risk_gate_requirement": 0.55},
            bundle_audit={"frozen_outputs_compressed": False, "comparison": {"mean_diff": 0.0}},
            research_vs={},
            platt={},
            equivalence={"empirical_frozen_threshold_when_research_passes": 0.49},
            risk_sim={"first_accepting_threshold": 0.45},
            production_replay={"calibration_actionable": 10, "risk_quality_pass": 0},
        )
        self.assertAlmostEqual(rec["mathematical_summary"]["gap"], 0.053, places=2)


class TestValidatorEdgeCases(unittest.TestCase):
    def test_fail_no_root_cause(self):
        v = validate_phase15g_results(
            bundle_audit={"trend_bars_evaluated": 1},
            platt={"synthetic_curve": [{}]},
            ceiling={"maximum_calibrated_confidence": 0.5},
            research_vs={"bars_compared": 1},
            equivalence={"synthetic_equivalence": {}},
            recovery={"no_production_changes": True},
        )
        self.assertIn("root_cause_identified", v["failed"])


class TestReportFileNames(unittest.TestCase):
    def test_expected_filenames(self):
        names = {
            "bundle_probability.json", "platt_curve.json", "confidence_ceiling.json",
            "riskgate_simulation.json", "research_vs_bundle.json",
            "threshold_equivalence.json", "recovery_recommendation.json",
            "phase15g_final_report.json",
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15g_reports(
                bundle_probability={}, platt_curve={}, confidence_ceiling={},
                riskgate_simulation={}, research_vs_bundle={},
                threshold_equivalence={}, recovery_recommendation={},
                final_report={},
                base_dir=tmp,
            )
            self.assertEqual({p.name for p in out.glob("*.json")}, names)


class TestConfidenceRiskMapper(unittest.TestCase):
    def test_blocks_below_55(self):
        from tradingbot.ml.risk_intelligence.confidence_risk_mapper import confidence_risk_multiplier
        mult, _ = confidence_risk_multiplier(0.50)
        self.assertEqual(mult, 0.0)

    def test_passes_at_55(self):
        from tradingbot.ml.risk_intelligence.confidence_risk_mapper import confidence_risk_multiplier
        mult, _ = confidence_risk_multiplier(0.55)
        self.assertGreater(mult, 0.0)


class TestPhase15GResult(unittest.TestCase):
    def test_to_dict(self):
        from tradingbot.ml.research.phase15g.orchestrator import Phase15GResult
        r = Phase15GResult("PASS", "READY_FOR_PHASE15H", "/tmp", "cause")
        self.assertEqual(r.to_dict()["phase"], "15G")


class TestHistogramBins(unittest.TestCase):
    def test_ten_bins(self):
        vals = list(np.linspace(0, 1, 100))
        h = histogram(vals, bins=10)
        self.assertEqual(len(h["counts"]), 10)


class TestSyntheticRawFields(unittest.TestCase):
    def test_engine_set(self):
        from tradingbot.ml.research.phase15g.platt_curve_analysis import _synthetic_raw
        r = _synthetic_raw(0.31)
        self.assertEqual(r.engine, "trend_rf_v40")
        self.assertAlmostEqual(r.raw_value, 0.31)


class TestRecoveryNoModify(unittest.TestCase):
    def test_all_outcomes_no_impl(self):
        from tradingbot.ml.research.phase15g.confidence_recovery import _OUTCOMES
        for key, val in _OUTCOMES.items():
            self.assertEqual(val["implementation"], "none_in_15g", key)


class TestCliScript(unittest.TestCase):
    def test_cli_parses(self):
        path = ROOT / "scripts" / "run_phase15g_confidence_analysis.py"
        self.assertIn("run_phase15g_analysis", path.read_text(encoding="utf-8"))

    def test_cli_main_guard(self):
        path = ROOT / "scripts" / "run_phase15g_confidence_analysis.py"
        self.assertIn("__main__", path.read_text(encoding="utf-8"))


class TestConfigDefaults(unittest.TestCase):
    def test_stride_default(self):
        from tradingbot.ml.research.phase15g.config import DEFAULT_STRIDE
        self.assertEqual(DEFAULT_STRIDE, 5)

    def test_platt_points(self):
        from tradingbot.ml.research.phase15g.config import PLATT_CURVE_POINTS
        self.assertGreater(PLATT_CURVE_POINTS, 10)


class TestValidatorChecks(unittest.TestCase):
    def test_check_keys(self):
        v = validate_phase15g_results(
            bundle_audit={"trend_bars_evaluated": 1},
            platt={"synthetic_curve": [{}]},
            ceiling={"maximum_calibrated_confidence": 0.5},
            research_vs={"bars_compared": 1},
            equivalence={"synthetic_equivalence": {}},
            recovery={"why_frozen_never_reaches_riskgate": "x", "no_production_changes": True},
        )
        self.assertIn("checks", v)
        self.assertEqual(len(v["checks"]), 7)


class TestRecoveryOutcomesExtended(unittest.TestCase):
    def test_outcome_a_threshold_mapping(self):
        rec = build_recovery_recommendation(
            ceiling={"maximum_calibrated_confidence": 0.49, "ceiling_below_risk_gate": True,
                     "risk_gate_requirement": 0.55},
            bundle_audit={"frozen_outputs_compressed": False, "comparison": {"mean_diff": 0.0}},
            research_vs={},
            platt={},
            equivalence={"empirical_frozen_threshold_when_research_passes": 0.48},
            risk_sim={},
            production_replay={"calibration_actionable": 5, "risk_quality_pass": 0},
        )
        self.assertEqual(rec["single_recommendation"]["outcome"], "A")


class TestBundleStatisticsStd(unittest.TestCase):
    def test_std_single_value(self):
        d = distribution_stats([0.5])
        self.assertEqual(d["std"], 0.0)


class TestRawConfidenceType(unittest.TestCase):
    def test_raw_confidence_fields(self):
        r = RawConfidence(
            raw_value=0.1, engine="trend_rf_v40", regime="TREND",
            model_probability=0.4, regime_strength=0.8, market_quality=0.7,
            session="london", volatility=50.0, volatility_state="normal",
            engine_signal="SELL",
        )
        self.assertEqual(r.engine_signal, "SELL")


class TestOrchestratorDataclass(unittest.TestCase):
    def test_fields(self):
        from tradingbot.ml.research.phase15g.orchestrator import Phase15GResult
        r = Phase15GResult("NEEDS_REVIEW", "NEEDS_REVIEW", "/x", "blocked")
        self.assertEqual(r.status, "NEEDS_REVIEW")


class TestReportGeneratorPaths(unittest.TestCase):
    def test_creates_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15g_reports(
                bundle_probability={"phase": "15G"}, platt_curve={}, confidence_ceiling={},
                riskgate_simulation={}, research_vs_bundle={},
                threshold_equivalence={}, recovery_recommendation={},
                final_report={},
                base_dir=tmp,
            )
            self.assertTrue(out.is_dir())


if __name__ == "__main__":
    unittest.main()
