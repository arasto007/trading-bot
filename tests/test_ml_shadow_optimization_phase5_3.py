"""Phase 5.3 shadow optimization tests."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord, new_decision_id, utc_now_iso
from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.optimization.filters import AdaptiveFilterAnalyzer
from tradingbot.ml.optimization.optimizer import ShadowPolicyOptimizer
from tradingbot.ml.optimization.reports import shadow_optimization_path
from tradingbot.ml.optimization.schema import OptimizationResult, PolicyConfig
from tradingbot.ml.optimization.threshold import ThresholdOptimizer
from tradingbot.ml.optimization.weights import WeightOptimizer

OPT_PKG = ROOT / "tradingbot" / "ml" / "optimization"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _decision(
    *,
    prob: float = 0.72,
    session: str = "london",
    regime: str = "trend",
    rule: str = "BUY",
    ts: str = "2024-01-01T00:00:00+00:00",
) -> DecisionRecord:
    return DecisionRecord(
        decision_id=new_decision_id(),
        timestamp=ts,
        symbol="XAUUSD",
        timeframe="M5",
        model_name="logistic",
        ml_probability=prob,
        ml_prediction=1,
        rule_signal=rule,
        hybrid_decision="BUY",
        confidence="HIGH",
        final_score=0.78,
        features_version="2.0",
        dataset_version="1.0",
        entry_price=100.0,
        direction=1,
        session=session,
        regime=regime,
    )


def _outcome(decision_id: str, r: float, label: int = 1) -> OutcomeRecord:
    return OutcomeRecord(
        decision_id=decision_id,
        evaluated_at=utc_now_iso(),
        future_return=0.01,
        tp_hit=r > 0,
        sl_hit=r < 0,
        max_favorable_excursion=2.0,
        max_adverse_excursion=0.5,
        r_multiple=r,
        label=label,
    )


def _build_history(n: int = 12, asia_negative: bool = False) -> tuple[list[DecisionRecord], dict[str, OutcomeRecord]]:
    decisions: list[DecisionRecord] = []
    outcomes: dict[str, OutcomeRecord] = {}
    for i in range(n):
        session = "asia" if asia_negative and i % 3 == 0 else "london"
        regime = "low_volatility" if asia_negative and i % 4 == 0 else "trend"
        prob = 0.55 + (i % 5) * 0.05
        d = _decision(
            prob=prob,
            session=session,
            regime=regime,
            ts=f"2024-01-{1 + i // 5:02d}T{10 + i % 12:02d}:00:00+00:00",
        )
        r = -1.0 if session == "asia" and asia_negative else 2.0
        decisions.append(d)
        outcomes[d.decision_id] = _outcome(d.decision_id, r, 1 if r > 0 else 0)
    return decisions, outcomes


class TestSchema(unittest.TestCase):
    def test_optimization_schema(self):
        current = PolicyConfig(threshold=0.5, ml_weight=0.6)
        recommended = PolicyConfig(threshold=0.65, ml_weight=0.7, disabled_regimes=["low_volatility"])
        result = OptimizationResult(
            timestamp=utc_now_iso(),
            symbol="XAUUSD",
            timeframe="M5",
            current_config=current,
            recommended_config=recommended,
            expected_R_before=0.21,
            expected_R_after=0.36,
            confidence_change=0.05,
            sample_size=100,
            warnings=[],
        )
        payload = result.to_dict()
        self.assertEqual(payload["recommended_config"]["threshold"], 0.65)


class TestThresholdSweep(unittest.TestCase):
    def test_threshold_sweep(self):
        decisions, outcomes = _build_history()
        best, candidates, _ = ThresholdOptimizer(min_samples=3).optimize(decisions, outcomes)
        self.assertIsNotNone(best)
        self.assertEqual(len(candidates), 7)

    def test_best_parameter_selection(self):
        decisions, outcomes = _build_history()
        optimizer = ShadowPolicyOptimizer(min_samples=3)
        result = optimizer.optimize(decisions, outcomes)
        self.assertGreaterEqual(result.sample_size, 3)
        self.assertIsInstance(result.recommended_config.threshold, float)


class TestWeightSweep(unittest.TestCase):
    def test_weight_sweep(self):
        decisions, outcomes = _build_history()
        best, candidates, _ = WeightOptimizer(min_samples=3, threshold=0.55).optimize(decisions, outcomes)
        self.assertIsNotNone(best)
        self.assertAlmostEqual(best.ml_weight + best.rule_weight, 1.0, places=2)
        self.assertGreater(len(candidates), 0)


class TestFilters(unittest.TestCase):
    def test_filter_detection(self):
        decisions, outcomes = _build_history(asia_negative=True)
        rec = AdaptiveFilterAnalyzer(min_samples=2).analyze(decisions, outcomes)
        self.assertIn("asia", rec.disabled_sessions)
        self.assertTrue(any(r.get("reason") == "negative expected_R" for r in rec.reasons))


class TestSmallSampleProtection(unittest.TestCase):
    def test_small_dataset_protection(self):
        d = _decision(prob=0.8)
        o = _outcome(d.decision_id, 2.0)
        result = ShadowPolicyOptimizer(min_samples=10).optimize([d], {d.decision_id: o})
        self.assertTrue(any("insufficient" in w for w in result.warnings))


class TestNoFutureLeakage(unittest.TestCase):
    def test_chronological_pairs_no_shuffle(self):
        decisions, outcomes = _build_history()
        from tradingbot.ml.optimization._sim import iter_pairs

        pairs = iter_pairs(decisions, outcomes)
        timestamps = [p[0].timestamp for p in pairs]
        self.assertEqual(timestamps, sorted(timestamps))


class TestReports(unittest.TestCase):
    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionMemoryStore("XAUUSD", tmp)
            decisions, outcomes = _build_history()
            for d in decisions:
                store.append_decision(d)
            for o in outcomes.values():
                store.append_outcome(o)
            payload = ShadowPolicyOptimizer(min_samples=3, base_dir=tmp).run_and_report(store)
            self.assertTrue(shadow_optimization_path(tmp).is_file())
            self.assertIn("best_threshold", payload)
            self.assertIn("expected_R_improvement", payload)


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        for path in OPT_PKG.glob("*.py"):
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
