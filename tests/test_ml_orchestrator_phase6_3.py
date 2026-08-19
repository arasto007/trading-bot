"""Phase 6.3 final strategy orchestrator tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.abtest.schema import WINNER_HYBRID, WINNER_RULE
from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, DECISION_WAIT
from tradingbot.ml.orchestrator.confidence_router import ConfidenceRouter
from tradingbot.ml.orchestrator.decision_engine import FinalDecisionEngine
from tradingbot.ml.orchestrator.ensemble import EnsembleEngine
from tradingbot.ml.orchestrator.explain import build_reasoning
from tradingbot.ml.orchestrator.logger import OrchestratorLogger
from tradingbot.ml.orchestrator.regime_gate import RegimeGate
from tradingbot.ml.orchestrator.risk_adjustment import RiskAdjustmentLayer
from tradingbot.ml.orchestrator.schema import OrchestratorConfig, OrchestratorSnapshot, StrategyMode
from tradingbot.ml.orchestrator.signals import extract_signals, signals_agree
from tradingbot.ml.orchestrator.strategy_selector import StrategySelector

ORCH_PKG = ROOT / "tradingbot" / "ml" / "orchestrator"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _snapshot(**overrides) -> OrchestratorSnapshot:
    base = OrchestratorSnapshot(
        timestamp="2024-03-01T10:00:00+00:00",
        symbol="XAUUSD",
        timeframe="M5",
        rule_signal=DECISION_BUY,
        ml_prediction=1,
        ml_probability=0.72,
        hybrid_decision=DECISION_BUY,
        hybrid_score=0.75,
        final_score=0.75,
        direction=1,
        session="london",
        regime="trend",
        features_snapshot={"volatility_regime": 0.4, "trend_strength": 30.0},
        ab_winner=WINNER_HYBRID,
        performance_state="HEALTHY",
        calibration_error=0.05,
        feature_drift_score=0.05,
        max_drawdown_r=5.0,
        loss_streak=0,
        paper_expectancy_r=0.5,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        for path in ORCH_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._safe(node.module)

    def test_no_risk_imports(self):
        for path in ORCH_PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.adapters.risk_gate", text)
            self.assertNotIn("tradingbot.risk", text)

    def test_no_execution_imports(self):
        for path in ORCH_PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.execution", text)
            self.assertNotIn("tradingbot.adapters.mt5_execution", text)

    def _safe(self, module: str) -> None:
        for prefix in FORBIDDEN:
            self.assertFalse(module.startswith(prefix), module)


class TestEnsemble(unittest.TestCase):
    def test_correct_ensemble_math(self):
        snap = _snapshot()
        engine = EnsembleEngine(OrchestratorConfig(ab_bias=0.05))
        contrib = engine.compute(snap)
        self.assertGreaterEqual(contrib.ml_weight, 0.3)
        self.assertLessEqual(contrib.ml_weight, 0.8)
        self.assertGreaterEqual(contrib.rule_weight, 0.2)
        self.assertLessEqual(contrib.rule_weight, 0.6)
        self.assertAlmostEqual(
            contrib.ml_weight + contrib.rule_weight + contrib.hybrid_weight,
            1.0,
            places=4,
        )
        self.assertGreater(contrib.ab_bias, 0)
        self.assertGreaterEqual(contrib.adjusted_score, -1.0)
        self.assertLessEqual(contrib.adjusted_score, 1.0)

    def test_ab_bias_integration(self):
        hybrid = EnsembleEngine().compute(_snapshot(ab_winner=WINNER_HYBRID))
        rule = EnsembleEngine().compute(_snapshot(ab_winner=WINNER_RULE))
        tie = EnsembleEngine().compute(_snapshot(ab_winner="NO_DIFFERENCE"))
        self.assertGreater(hybrid.ab_bias, tie.ab_bias)
        self.assertLess(rule.ab_bias, tie.ab_bias)


class TestRegimeGate(unittest.TestCase):
    def test_regime_gating_logic(self):
        trend = RegimeGate().evaluate(_snapshot(regime="trend"))
        self.assertTrue(trend.allow_ml)
        self.assertFalse(trend.force_wait)

        range_gate = RegimeGate().evaluate(_snapshot(regime="range"))
        self.assertTrue(range_gate.favor_rule)

        news = RegimeGate().evaluate(
            _snapshot(features_snapshot={"news_event": 1.0, "spread_spike": 0.8})
        )
        self.assertTrue(news.force_wait)
        self.assertEqual(news.regime, "news")

        high_vol = RegimeGate().evaluate(_snapshot(regime="high_volatility"))
        self.assertTrue(high_vol.reduce_frequency)


class TestRiskAdjustment(unittest.TestCase):
    def test_risk_reduction_behavior(self):
        layer = RiskAdjustmentLayer(OrchestratorConfig())
        normal = layer.evaluate(_snapshot(), 0.6)
        self.assertEqual(normal.risk_state, "NORMAL")
        self.assertEqual(normal.score_multiplier, 1.0)

        drawdown = layer.evaluate(_snapshot(max_drawdown_r=15.0), 0.6)
        self.assertLess(drawdown.score_multiplier, 1.0)
        self.assertIn("Drawdown", " ".join(drawdown.reasons))

        streak = layer.evaluate(_snapshot(loss_streak=6), 0.5)
        self.assertTrue(streak.reduce_frequency)

        spread = layer.evaluate(
            _snapshot(features_snapshot={"spread_regime": 0.9}),
            0.6,
        )
        self.assertTrue(spread.force_wait)


class TestConfidenceRouter(unittest.TestCase):
    def test_confidence_routing_correctness(self):
        router = ConfidenceRouter()
        snap = _snapshot()
        signals = extract_signals(snap)
        self.assertTrue(signals_agree(signals))
        level = router.route(snap, 0.7, strategy_mode="ENSEMBLE")
        self.assertIn(level, ("HIGH", "EXTREME"))

        degraded = router.route(
            _snapshot(performance_state="DEGRADED", calibration_error=0.25),
            0.7,
            strategy_mode="ENSEMBLE",
        )
        self.assertIn(degraded, ("LOW", "MEDIUM"))


class TestStrategySelector(unittest.TestCase):
    def test_strategy_selection_correctness(self):
        selector = StrategySelector()
        self.assertEqual(
            selector.select(_snapshot(performance_state="FAILED")),
            StrategyMode.SAFE_MODE.value,
        )
        self.assertEqual(
            selector.select(_snapshot(ab_winner=WINNER_RULE, paper_expectancy_r=0.2)),
            StrategyMode.RULE_ONLY.value,
        )
        self.assertEqual(
            selector.select(_snapshot(ab_winner=WINNER_HYBRID, paper_expectancy_r=0.5)),
            StrategyMode.ENSEMBLE.value,
        )


class TestDecisionEngine(unittest.TestCase):
    def test_deterministic_output(self):
        snap = _snapshot()
        engine = FinalDecisionEngine(OrchestratorConfig())
        d1 = engine.generate_final_decision(snap)
        d2 = engine.generate_final_decision(snap)
        self.assertEqual(d1.action, d2.action)
        self.assertEqual(d1.confidence, d2.confidence)
        self.assertEqual(d1.ensemble_score, d2.ensemble_score)

    def test_no_lookahead(self):
        snap = _snapshot(timestamp="2024-03-01T10:00:00+00:00")
        decision = FinalDecisionEngine().generate_final_decision(snap)
        self.assertEqual(decision.timestamp, snap.timestamp)
        self.assertNotIn("future", json.dumps(decision.trace))

    def test_safe_mode_activation(self):
        snap = _snapshot(performance_state="FAILED")
        decision = FinalDecisionEngine().generate_final_decision(snap)
        self.assertEqual(decision.active_strategy, StrategyMode.SAFE_MODE.value)
        self.assertEqual(decision.action, DECISION_WAIT)

    def test_bullish_buy_decision(self):
        snap = _snapshot()
        decision = FinalDecisionEngine().generate_final_decision(snap)
        self.assertEqual(decision.action, DECISION_BUY)
        self.assertTrue(any("FINAL: BUY" in r for r in decision.reasoning))


class TestLogger(unittest.TestCase):
    def test_logging_correctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = OrchestratorLogger(base_dir=tmp)
            snap = _snapshot()
            decision = FinalDecisionEngine().generate_final_decision(snap)
            path = logger.log(decision)
            self.assertTrue(path.is_file())
            rows = logger.read_all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], decision.action)
            self.assertIn("trace", rows[0])
            self.assertIn("source_contributions", rows[0])


class TestExplain(unittest.TestCase):
    def test_reasoning_chain(self):
        snap = _snapshot()
        contrib = EnsembleEngine().compute(snap)
        reasons = build_reasoning(
            snap,
            contrib,
            action=DECISION_BUY,
            confidence="HIGH",
            active_strategy="ENSEMBLE",
            regime="trend",
            risk_reasons=[],
            regime_reasons=["Trend regime — ML allowed"],
        )
        text = "\n".join(reasons)
        self.assertIn("ML bullish", text)
        self.assertIn("A/B winner = hybrid", text)
        self.assertIn("FINAL: BUY", text)


if __name__ == "__main__":
    unittest.main()
