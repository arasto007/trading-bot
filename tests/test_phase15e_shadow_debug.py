"""Phase 15E — shadow signal failure diagnosis tests."""

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

from tradingbot.ml.phase15e_debug.confidence_analysis import ConfidenceAnalyzer
from tradingbot.ml.phase15e_debug.config import MIN_CONFIDENCE_THRESHOLD, reports_dir
from tradingbot.ml.phase15e_debug.legacy_diff import LegacyDiffEngine
from tradingbot.ml.phase15e_debug.regime_analysis import RegimeActivationAnalyzer
from tradingbot.ml.phase15e_debug.report_generator import write_phase15e_reports
from tradingbot.ml.phase15e_debug.root_cause import (
    ROOT_CAUSES,
    build_shadow_activation_report,
    classify_root_cause,
)
from tradingbot.ml.phase15e_debug.signal_funnel import SignalFunnel
from tradingbot.ml.phase15e_debug.stage_probe import StageProbeResult

PHASE15E_PKG = ROOT / "tradingbot" / "ml" / "phase15e_debug"


def _probe(**kwargs: object) -> StageProbeResult:
    defaults = {
        "timestamp": "2022-01-01T10:00:00",
        "unified_ok": True,
        "regime": "RANGE",
        "decision_14_1_action": "HOLD",
        "calibrated_action": "HOLD",
        "risk_allowed": False,
        "quality_allowed": False,
        "kernel_final_action": "HOLD",
    }
    defaults.update(kwargs)
    return StageProbeResult(**defaults)  # type: ignore[arg-type]


def _funnel_with_legacy_only() -> tuple[SignalFunnel, RegimeActivationAnalyzer, ConfidenceAnalyzer, LegacyDiffEngine]:
    funnel = SignalFunnel()
    regime = RegimeActivationAnalyzer()
    conf = ConfidenceAnalyzer()
    diff = LegacyDiffEngine()
    for i in range(100):
        p = _probe(
            timestamp=f"2022-01-{i % 28 + 1:02d}",
            legacy_signal="BUY" if i < 20 else None,
            regime="HIGH_VOLATILITY" if i < 60 else "RANGE",
            raw_confidence=0.3,
            calibrated_confidence=0.4,
            decision_14_1_confidence=0.45,
            quality_score=0.4,
        )
        funnel.add(p)
        regime.probes.append(p)
        conf.probes.append(p)
        diff.probes.append(p)
    return funnel, regime, conf, diff


class TestStageProbeResult(unittest.TestCase):
    def test_to_dict(self):
        d = _probe().to_dict()
        self.assertIn("regime", d)


class TestSignalFunnel(unittest.TestCase):
    def test_empty(self):
        rep = SignalFunnel().build_report()
        self.assertEqual(rep["bars_evaluated"], 0)

    def test_funnel_stages(self):
        f = SignalFunnel()
        f.add(_probe(
            decision_14_1_action="BUY", calibrated_action="BUY",
            risk_allowed=True, quality_allowed=True,
            kernel_final_action="BUY", trading_signal="BUY",
            legacy_signal="BUY",
        ))
        rep = f.build_report()
        self.assertEqual(rep["stage_summary"]["trading_signal_buy_sell"], 1)

    def test_drop_tracking(self):
        f = SignalFunnel()
        f.add(_probe(drop_stage="calibration_14_2a", drop_reason="blocked"))
        self.assertIn("calibration_14_2a", f.build_report()["drop_stages"])

    def test_legacy_count(self):
        f = SignalFunnel()
        f.add(_probe(legacy_signal="SELL"))
        self.assertEqual(f.build_report()["legacy_signals"], 1)


class TestRegimeAnalysis(unittest.TestCase):
    def test_distribution(self):
        r = RegimeActivationAnalyzer()
        r.probes = [_probe(regime="TREND"), _probe(regime="RANGE"), _probe(regime="RANGE")]
        rep = r.build_report()
        self.assertAlmostEqual(rep["regime_distribution"]["RANGE"], 2 / 3, places=3)

    def test_heatmap(self):
        r = RegimeActivationAnalyzer()
        r.probes = [_probe(regime="TREND", trading_signal="BUY")]
        self.assertIn("TREND", r.build_report()["heatmap"])


class TestConfidenceAnalysis(unittest.TestCase):
    def test_histogram(self):
        c = ConfidenceAnalyzer()
        c.probes = [_probe(raw_confidence=0.4, calibrated_confidence=0.5, quality_score=0.6)]
        rep = c.build_report()
        self.assertTrue(rep["raw_histogram"])

    def test_below_threshold(self):
        c = ConfidenceAnalyzer()
        c.probes = [_probe(raw_confidence=0.2, calibrated_confidence=0.3, quality_score=0.4)]
        rep = c.build_report()
        self.assertGreater(rep["pct_below_min_confidence_0_55"], 0)

    def test_threshold_constant(self):
        self.assertEqual(MIN_CONFIDENCE_THRESHOLD, 0.55)


class TestLegacyDiff(unittest.TestCase):
    def test_missing_ml(self):
        d = LegacyDiffEngine()
        d.probes = [_probe(legacy_signal="BUY", trading_signal=None, drop_stage="decision_14_1")]
        rep = d.build_report()
        self.assertEqual(rep["missing_ml_when_legacy_active"], 1)

    def test_divergence_points(self):
        d = LegacyDiffEngine()
        d.probes = [_probe(legacy_signal="BUY", drop_stage="risk_14_2b")]
        self.assertIn("risk_14_2b", d.build_report()["divergence_points"])


class TestRootCause(unittest.TestCase):
    def test_classify_returns_primary(self):
        funnel, regime, conf, diff = _funnel_with_legacy_only()
        root = classify_root_cause(funnel, regime, conf, diff)
        self.assertIn(root["primary_cause"], list(ROOT_CAUSES) + ["UNKNOWN"])
        self.assertIsInstance(root["root_cause"], list)

    def test_activation_failed(self):
        funnel, regime, conf, diff = _funnel_with_legacy_only()
        root = classify_root_cause(funnel, regime, conf, diff)
        act = build_shadow_activation_report(funnel, root)
        self.assertEqual(act["activation_status"], "FAILED")
        self.assertEqual(act["ml_signals"], 0)

    def test_fix_recommendation(self):
        funnel, regime, conf, diff = _funnel_with_legacy_only()
        root = classify_root_cause(funnel, regime, conf, diff)
        self.assertTrue(root["fix_recommendation"])

    def test_safe_to_enable_false_when_no_ml(self):
        funnel, regime, conf, diff = _funnel_with_legacy_only()
        root = classify_root_cause(funnel, regime, conf, diff)
        self.assertFalse(root["safe_to_enable_ml_live"])


class TestReportGenerator(unittest.TestCase):
    def test_writes_all_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15e_reports(
                funnel_report={"bars_evaluated": 1},
                activation_report={"activation_status": "FAILED"},
                regime_report={"heatmap": {}},
                confidence_report={"raw_histogram": []},
                legacy_diff_report={"legacy_signals": 1},
                root_cause_report={"primary_cause": "CONFIDENCE_COLLAPSE"},
                final_report={"shadow_mode_issue": True},
                base_dir=tmp,
            )
            self.assertTrue((out / "final_debug_report.json").is_file())
            self.assertTrue((reports_dir(tmp) / "signal_funnel_report.json").is_file())

    def test_json_parseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_phase15e_reports(
                funnel_report={"x": 1},
                activation_report={"x": 1},
                regime_report={"x": 1},
                confidence_report={"x": 1},
                legacy_diff_report={"x": 1},
                root_cause_report={"x": 1},
                final_report={"shadow_mode_issue": True},
                base_dir=tmp,
            )
            data = json.loads((out / "final_debug_report.json").read_text())
            self.assertTrue(data["shadow_mode_issue"])


class TestSafetyGuards(unittest.TestCase):
    def test_no_order_send(self):
        for py in PHASE15E_PKG.glob("*.py"):
            self.assertNotIn("order_send(", py.read_text(encoding="utf-8"))

    def test_no_mt5(self):
        for py in PHASE15E_PKG.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            self.assertNotIn("MetaTrader5", src)
            self.assertNotIn("mt5.", src)

    def test_no_kernel_modify(self):
        for py in PHASE15E_PKG.glob("*.py"):
            self.assertNotIn("TradingKernel", py.read_text(encoding="utf-8"))

    def test_ast_no_forbidden(self):
        for py in PHASE15E_PKG.glob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ("order_send",))


class TestDeterminism(unittest.TestCase):
    def test_funnel_deterministic(self):
        f1 = SignalFunnel()
        f2 = SignalFunnel()
        probes = [_probe(decision_14_1_action="BUY", calibrated_action="HOLD") for _ in range(5)]
        for p in probes:
            f1.add(p)
            f2.add(p)
        self.assertEqual(f1.build_report(), f2.build_report())


class TestOrchestratorIntegration(unittest.TestCase):
    def test_candles_missing_raises(self):
        from tradingbot.ml.phase15e_debug.orchestrator import run_phase15e_shadow_debug
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                run_phase15e_shadow_debug(base_dir=tmp, days=30, stride=50, warmup=100)

    def test_run_with_mocked_probe(self):
        from tradingbot.ml.phase15e_debug import orchestrator as orch
        probe = _probe(legacy_signal="BUY", trading_signal=None, drop_stage="decision_14_1")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(orch.CandleStore, "load", return_value=pd.DataFrame({
                "open": [1.0] * 500, "high": [1.1] * 500, "low": [0.9] * 500,
                "close": np.linspace(2300, 2310, 500), "volume": [100] * 500,
            }, index=pd.date_range("2022-01-01", periods=500, freq="5min", tz="UTC"))):
                with mock.patch.object(orch, "probe_bar", return_value=probe):
                    with mock.patch.object(orch, "LegacyStrategyRegistry"):
                        with mock.patch.object(orch, "build_ml_kernel_stack"):
                            with mock.patch.object(orch, "build_kernel_adapter"):
                                result = orch.run_phase15e_shadow_debug(
                                    base_dir=tmp, days=30, stride=100, warmup=50,
                                )
            self.assertEqual(result.status, "DIAGNOSED")
            self.assertTrue((reports_dir(tmp) / "final_debug_report.json").is_file())


if __name__ == "__main__":
    unittest.main()
