"""Phase 6.4 deployment readiness tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.deployment.deployment_policy import DeploymentPolicy
from tradingbot.ml.deployment.kill_switch import KillSwitch
from tradingbot.ml.deployment.live_readiness_engine import LiveReadinessEngine
from tradingbot.ml.deployment.logger import DeploymentLogger
from tradingbot.ml.deployment.readiness_scoring import ReadinessScorer
from tradingbot.ml.deployment.risk_gates import DeploymentRiskGates
from tradingbot.ml.deployment.schema import DeploymentPolicyConfig, ReadinessMetrics, ReadinessStatus
from tradingbot.ml.deployment.shadow_validation import ShadowValidator
from tradingbot.ml.deployment.stability_checker import StabilityChecker
from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, DECISION_WAIT
from tradingbot.ml.memory.schema import DecisionRecord, new_decision_id

DEPLOY_PKG = ROOT / "tradingbot" / "ml" / "deployment"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _metrics(**overrides) -> ReadinessMetrics:
    base = ReadinessMetrics(
        paper_win_rate=0.62,
        paper_expectancy_r=0.4,
        paper_max_drawdown_r=12.0,
        paper_sharpe=1.2,
        paper_trade_count=120,
        monitoring_health=0.85,
        expected_r=0.35,
        performance_state="HEALTHY",
        feature_drift_score=0.08,
        calibration_error=0.06,
        ab_winner="HYBRID_BETTER",
        ab_confidence="HIGH",
        ab_sample_size=150,
        ab_improvement=0.08,
        degradation_status="HEALTHY",
        degradation_drop_pct=0.05,
        shadow_validation_score=0.78,
        shadow_stability_score=0.82,
        shadow_noise_ratio=0.12,
        stability_state="STABLE",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _decision(i: int, *, hybrid: str = DECISION_BUY, rule: str = DECISION_BUY, ml: int = 1) -> DecisionRecord:
    return DecisionRecord(
        decision_id=new_decision_id(),
        timestamp=f"2024-03-{1 + i // 10:02d}T{10 + i % 10:02d}:00:00+00:00",
        symbol="XAUUSD",
        timeframe="M5",
        model_name="logistic",
        ml_probability=0.7,
        ml_prediction=ml,
        rule_signal=rule,
        hybrid_decision=hybrid,
        confidence="HIGH",
        final_score=0.75,
        features_version="2.0",
        dataset_version="1.0",
        direction=1,
        session="london",
        regime="trend",
        features_snapshot={"trend_strength": 30.0, "volatility_regime": 0.4},
    )


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        for path in DEPLOY_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._safe(node.module)

    def test_no_risk_imports(self):
        for path in DEPLOY_PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.adapters.risk_gate", text)
            self.assertNotIn("tradingbot.risk", text)

    def test_no_execution_imports(self):
        for path in DEPLOY_PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.execution", text)
            self.assertNotIn("tradingbot.adapters.mt5_execution", text)

    def _safe(self, module: str) -> None:
        for prefix in FORBIDDEN:
            self.assertFalse(module.startswith(prefix), module)


class TestScoring(unittest.TestCase):
    def test_correct_scoring_math(self):
        scorer = ReadinessScorer(DeploymentPolicyConfig())
        breakdown = scorer.score(_metrics())
        self.assertGreaterEqual(breakdown.composite_score, 0.0)
        self.assertLessEqual(breakdown.composite_score, 1.0)
        expected = (
            0.25 * breakdown.paper_trading_performance
            + 0.20 * breakdown.monitoring_health
            + 0.20 * breakdown.feature_stability
            + 0.15 * breakdown.ab_consistency
            + 0.10 * breakdown.calibration_quality
            + 0.10 * breakdown.degradation_component
        )
        self.assertAlmostEqual(breakdown.composite_score, round(expected, 6), places=4)

    def test_threshold_classification(self):
        scorer = ReadinessScorer(DeploymentPolicyConfig())
        self.assertEqual(scorer.classify(0.85), ReadinessStatus.LIVE_READY.value)
        self.assertEqual(scorer.classify(0.70), ReadinessStatus.CONDITIONAL_READY.value)
        self.assertEqual(scorer.classify(0.45), ReadinessStatus.NOT_READY.value)


class TestKillSwitch(unittest.TestCase):
    def test_kill_switch_activation(self):
        ks = KillSwitch()
        allow = ks.evaluate(ReadinessStatus.LIVE_READY.value, [])
        block = ks.evaluate(ReadinessStatus.NOT_READY.value, ["High drawdown"], hard_fail=True)
        self.assertFalse(allow.block_deployment)
        self.assertTrue(block.block_deployment)
        self.assertEqual(block.flag, "BLOCK")


class TestStability(unittest.TestCase):
    def test_stability_detection(self):
        stable = [_decision(i) for i in range(30)]
        report = StabilityChecker().analyze(stable)
        self.assertEqual(report.stability_state, "STABLE")

        unstable = []
        for i in range(40):
            regime = "trend" if i % 2 == 0 else "range"
            d = _decision(i, hybrid=DECISION_BUY if i % 3 else DECISION_SELL)
            d.regime = regime
            unstable.append(d)
        report2 = StabilityChecker(regime_shift_threshold=3).analyze(unstable)
        self.assertIn(report2.stability_state, ("UNSTABLE", "CRITICAL"))


class TestDriftIntegration(unittest.TestCase):
    def test_drift_integration(self):
        gates = DeploymentRiskGates(DeploymentPolicyConfig(max_drift_score=0.25))
        ok = gates.evaluate(_metrics(feature_drift_score=0.10))
        fail = gates.evaluate(_metrics(feature_drift_score=0.30))
        self.assertFalse(ok.hard_fail)
        self.assertTrue(fail.hard_fail)
        self.assertIn("Feature drift HIGH", fail.flags)


class TestShadowValidation(unittest.TestCase):
    def test_shadow_validation_correctness(self):
        decisions = [_decision(i) for i in range(50)]
        result = ShadowValidator(window=50).validate(decisions)
        self.assertEqual(result.sample_count, 50)
        self.assertGreater(result.validation_score, 0.0)
        self.assertGreaterEqual(result.stability_score, 0.0)
        self.assertLessEqual(result.noise_ratio, 1.0)


class TestEngine(unittest.TestCase):
    def test_deterministic_output(self):
        engine = LiveReadinessEngine()
        metrics = _metrics()
        r1 = engine.evaluate_readiness("XAUUSD", "M5", metrics=metrics, write_report=False)
        r2 = engine.evaluate_readiness("XAUUSD", "M5", metrics=metrics, write_report=False)
        self.assertEqual(r1.status, r2.status)
        self.assertEqual(r1.score, r2.score)

    def test_no_lookahead(self):
        metrics = _metrics()
        report = LiveReadinessEngine().evaluate_readiness(
            "XAUUSD", "M5", metrics=metrics, write_report=False
        )
        self.assertNotIn("future", json.dumps(report.trace))

    def test_not_ready_on_hard_gates(self):
        metrics = _metrics(
            paper_max_drawdown_r=30.0,
            expected_r=-0.5,
            feature_drift_score=0.35,
        )
        report = LiveReadinessEngine().evaluate_readiness(
            "XAUUSD", "M5", metrics=metrics, write_report=False
        )
        self.assertEqual(report.status, ReadinessStatus.NOT_READY.value)
        self.assertTrue(report.kill_switch_active)


class TestLogger(unittest.TestCase):
    def test_logging_correctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = LiveReadinessEngine(base_dir=tmp)
            report = engine.evaluate_readiness("XAUUSD", "M5", metrics=_metrics())
            logger = DeploymentLogger(base_dir=tmp)
            payload = logger.read()
            self.assertEqual(payload["status"], report.status)
            self.assertIn("scoring", payload)
            self.assertIn("trace", payload)
            self.assertIn("risk_flags", payload)


if __name__ == "__main__":
    unittest.main()
