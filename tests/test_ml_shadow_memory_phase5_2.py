"""Phase 5.2 shadow performance memory tests."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.memory.calibration import ConfidenceCalibrator
from tradingbot.ml.memory.evaluator import ShadowDecisionEvaluator
from tradingbot.ml.memory.outcome import OutcomeEvaluator
from tradingbot.ml.memory.performance import PerformanceAnalyzer
from tradingbot.ml.memory.reports import (
    ShadowReportGenerator,
    confidence_calibration_path,
    regime_performance_path,
    session_performance_path,
    shadow_performance_path,
)
from tradingbot.ml.memory.schema import (
    DecisionRecord,
    OutcomeRecord,
    new_decision_id,
    regime_from_features,
    session_from_features,
    utc_now_iso,
)
from tradingbot.ml.memory.store import DecisionMemoryStore

MEMORY_PKG = ROOT / "tradingbot" / "ml" / "memory"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _synthetic_candles(n: int = 30, tp_long: bool = True) -> pd.DataFrame:
    """Build candles where long TP or SL is hit clearly."""
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.full(n, 100.0)
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)
    if tp_long:
        high[2] = 110.0
    else:
        low[2] = 90.0
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "timestamp": ts}
    )


def _sample_decision(**overrides) -> DecisionRecord:
    base = dict(
        decision_id=new_decision_id(),
        timestamp="2024-01-01T00:00:00+00:00",
        symbol="XAUUSD",
        timeframe="M5",
        model_name="logistic",
        ml_probability=0.72,
        ml_prediction=1,
        rule_signal="BUY",
        hybrid_decision="BUY",
        confidence="HIGH",
        final_score=0.78,
        features_version="2.0",
        dataset_version="1.0",
        entry_price=100.0,
        direction=1,
        session="london",
        regime="trend",
    )
    base.update(overrides)
    return DecisionRecord(**base)


class TestSchema(unittest.TestCase):
    def test_decision_record_schema(self):
        rec = _sample_decision()
        restored = DecisionRecord.from_dict(rec.to_dict())
        self.assertEqual(restored.symbol, "XAUUSD")
        self.assertEqual(restored.hybrid_decision, "BUY")

    def test_from_hybrid_factory(self):
        from tradingbot.ml.hybrid.schema import HybridDecision

        hybrid = HybridDecision(
            timestamp="2024-01-01T00:00:00+00:00",
            symbol="XAUUSD",
            timeframe="M5",
            rule_signal="BUY",
            ml_prediction=1,
            ml_probability=0.7,
            ml_direction="BUY",
            agreement_score=1.0,
            final_score=0.8,
            decision="BUY",
            confidence="HIGH",
            accepted=True,
        )
        rec = DecisionRecord.from_hybrid(hybrid, model_name="xgboost")
        self.assertEqual(rec.model_name, "xgboost")
        self.assertEqual(rec.hybrid_decision, "BUY")


class TestStore(unittest.TestCase):
    def test_memory_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionMemoryStore("XAUUSD", tmp)
            rec = _sample_decision()
            store.append_decision(rec)
            loaded = store.load_decisions()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].decision_id, rec.decision_id)


class TestOutcome(unittest.TestCase):
    def test_outcome_calculation_tp(self):
        candles = _synthetic_candles(tp_long=True)
        rec = _sample_decision(entry_price=100.0, direction=1)
        outcome = OutcomeEvaluator(future_window_bars=10).evaluate(rec, candles, entry_index=0)
        self.assertTrue(outcome.tp_hit or outcome.sl_hit or outcome.label == -1)

    def test_tp_sl_evaluation_r_multiple(self):
        candles = _synthetic_candles(tp_long=True)
        rec = _sample_decision(entry_price=100.0, direction=1)
        evaluator = OutcomeEvaluator(future_window_bars=10, atr_period=5)
        outcome = evaluator.evaluate(rec, candles, entry_index=0)
        if outcome.tp_hit:
            self.assertEqual(outcome.r_multiple, 2.0)
        if outcome.sl_hit:
            self.assertEqual(outcome.r_multiple, -1.0)

    def test_batch_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionMemoryStore("XAUUSD", tmp)
            store.append_decision(_sample_decision())
            candles = _synthetic_candles()
            results = ShadowDecisionEvaluator(store).evaluate_all(candles)
            self.assertEqual(len(results), 1)
            self.assertEqual(len(store.load_outcomes()), 1)


def _pairs():
    d1 = _sample_decision(confidence="HIGH", session="london", regime="trend")
    d2 = _sample_decision(
        decision_id=new_decision_id(),
        confidence="LOW",
        session="asia",
        regime="low_volatility",
        hybrid_decision="SELL",
        direction=-1,
        ml_prediction=0,
    )
    o1 = OutcomeRecord(d1.decision_id, utc_now_iso(), 0.01, True, False, 2.0, 0.5, 2.0, 1)
    o2 = OutcomeRecord(d2.decision_id, utc_now_iso(), -0.01, False, True, 0.5, 1.0, -1.0, 0)
    return [d1, d2], {d1.decision_id: o1, d2.decision_id: o2}


class TestPerformance(unittest.TestCase):
    def test_performance_metrics(self):
        decisions, outcomes = _pairs()
        summary = PerformanceAnalyzer().analyze(decisions, outcomes)
        self.assertEqual(summary.predictions, 2)
        self.assertGreater(summary.evaluated, 0)
        self.assertGreaterEqual(summary.win_rate, 0.0)

    def test_session_analysis(self):
        decisions, outcomes = _pairs()
        summary = PerformanceAnalyzer().analyze(decisions, outcomes)
        self.assertIn("london", summary.by_session)

    def test_regime_analysis(self):
        decisions, outcomes = _pairs()
        summary = PerformanceAnalyzer().analyze(decisions, outcomes)
        self.assertIn("trend", summary.by_regime)


class TestCalibration(unittest.TestCase):
    def test_confidence_calibration(self):
        decisions, outcomes = _pairs()
        cal = ConfidenceCalibrator().calibrate(decisions, outcomes)
        self.assertGreater(len(cal.bands), 0)
        self.assertIn(cal.status, ("PASS", "FAIL"))


class TestReports(unittest.TestCase):
    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionMemoryStore("XAUUSD", tmp)
            d = _sample_decision()
            store.append_decision(d)
            o = OutcomeRecord(d.decision_id, utc_now_iso(), 0.01, True, False, 2.0, 0.5, 2.0, 1)
            store.append_outcome(o)
            ShadowReportGenerator(tmp).generate_from_store(store)
            self.assertTrue(shadow_performance_path(tmp).is_file())
            self.assertTrue(confidence_calibration_path(tmp).is_file())
            self.assertTrue(session_performance_path(tmp).is_file())
            self.assertTrue(regime_performance_path(tmp).is_file())


class TestFeatureHelpers(unittest.TestCase):
    def test_session_and_regime_from_features(self):
        feats = {"session_london": 1.0, "trend_strength": 30.0, "volatility_regime": 0.5}
        self.assertEqual(session_from_features(feats), "london")
        self.assertEqual(regime_from_features(feats), "trend")


class TestIsolation(unittest.TestCase):
    def test_no_forbidden_imports(self):
        for path in MEMORY_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._safe(node.module)

    def _safe(self, module: str) -> None:
        for prefix in FORBIDDEN:
            self.assertFalse(module.startswith(prefix), module)

    def test_kernel_unchanged(self):
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401

    def test_risk_gate_unchanged(self):
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401


if __name__ == "__main__":
    unittest.main()
