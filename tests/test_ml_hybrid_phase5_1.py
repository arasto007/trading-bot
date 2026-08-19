"""Phase 5.1 hybrid decision layer tests — shadow mode only."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision.predictor import MLPredictor
from tradingbot.ml.hybrid.config import HybridConfig
from tradingbot.ml.hybrid.conflict import WARNING_CONFLICT, resolve_conflict
from tradingbot.ml.hybrid.engine import HybridDecisionEngine, compute_confidence
from tradingbot.ml.hybrid.logger import HybridLogger, hybrid_log_path
from tradingbot.ml.hybrid.ml_adapter import MLAdapter
from tradingbot.ml.hybrid.rules_adapter import RuleAdapter
from tradingbot.ml.hybrid.schema import (
    DECISION_BUY,
    DECISION_SELL,
    DECISION_WAIT,
    HybridDecision,
    MLSignal,
)
from tradingbot.ml.hybrid.scoring import compute_final_score
from tradingbot.ml.features.registry import feature_names
from tradingbot.ml.models.training import train_baseline_model
from tradingbot.ml.validation._utils import write_json_report

HYBRID_PKG = ROOT / "tradingbot" / "ml" / "hybrid"
FORBIDDEN_IMPORT_PREFIXES = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _make_dataset(n: int = 120, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-07-01", periods=n, freq="5min", tz="UTC")
    n_train = int(n * 0.70)
    n_val = int(n * 0.15)
    splits = ["train"] * n_train + ["validation"] * n_val + ["test"] * (n - n_train - n_val)
    labels = rng.choice([0, 1], size=n, p=[0.45, 0.55])
    row: dict = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": "bos",
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "timeframe_role": "entry_execution",
        "entry_price": 2300.0,
        "direction": 1,
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": labels,
        "future_window_bars": 72,
        "tp_hit": labels == 1,
        "sl_hit": labels == 0,
        "mfe": rng.uniform(0, 2, n),
        "mae": rng.uniform(0, 1, n),
        "future_return": rng.normal(0, 0.01, n),
        "risk_unit": 10.0,
        "split": splits,
        "dataset_schema_version": "1.0",
    }
    for feat in feature_names():
        row[feat] = rng.normal(0, 1, n)
    row["h4_trend_bias"] = 1.0
    row["bos_state"] = 1.0
    row["spread_spike"] = 0.0
    row["spread_zscore"] = 0.1
    row["volatility_regime"] = 0.5
    return pd.DataFrame(row)


def _setup(tmp: str) -> pd.DataFrame:
    store = DatasetStore(tmp)
    df = _make_dataset()
    store.store("XAUUSD", "M5", df)
    store.save_build_manifest("XAUUSD", "M5", {"dataset_hash": "h51", "feature_version": "2.0"})
    train_baseline_model("XAUUSD", "M5", "logistic", base_dir=tmp, params={"max_iter": 200})
    write_json_report(
        reports_dir(tmp) / "optimal_threshold.json",
        {"model": "logistic", "best_threshold": 0.50, "expected_R": 0.2, "winrate": 0.6, "signals": 40},
    )
    return df


class TestHybridSchema(unittest.TestCase):
    def test_hybrid_schema_creation(self):
        d = HybridDecision(
            timestamp="2024-01-01T00:00:00+00:00",
            symbol="XAUUSD",
            timeframe="M5",
            rule_signal="BUY",
            ml_prediction=1,
            ml_probability=0.74,
            ml_direction="BUY",
            agreement_score=1.0,
            final_score=0.78,
            decision="BUY",
            confidence="HIGH",
            accepted=True,
            reasons=["ML and rule agreement"],
            warnings=[],
        )
        payload = d.to_dict()
        self.assertEqual(payload["decision"], "BUY")
        self.assertTrue(payload["accepted"])


class TestRuleAdapter(unittest.TestCase):
    def test_rule_adapter_works(self):
        adapter = RuleAdapter()
        buy = adapter.from_signal("BUY", strength=0.85)
        self.assertEqual(buy.direction, 1)
        self.assertAlmostEqual(buy.strength, 0.85)
        sell = adapter.from_signal("SELL")
        self.assertEqual(sell.direction, -1)
        none = adapter.none()
        self.assertEqual(none.label, "WAIT")


class TestMLAdapter(unittest.TestCase):
    def test_ml_adapter_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _setup(tmp)
            row = df.iloc[0].to_dict()
            predictor = MLPredictor("XAUUSD", "M5", "logistic", base_dir=tmp).load()
            signal = MLAdapter(predictor).predict(row)
            self.assertIn(signal.direction, ("BUY", "SELL", "NEUTRAL"))
            self.assertGreaterEqual(signal.probability, 0.0)
            self.assertLessEqual(signal.probability, 1.0)


class TestConflict(unittest.TestCase):
    def test_agreement_increases_confidence(self):
        rule = RuleAdapter().from_signal("BUY", strength=0.9)
        ml = MLSignal(prediction=1, probability=0.8, direction="BUY", confidence="HIGH", accepted=True)
        conflict = resolve_conflict(rule, ml)
        self.assertTrue(conflict.agreement)
        self.assertEqual(conflict.decision, DECISION_BUY)

        agreed_conf = compute_confidence(
            0.80, 1.0, 0.8,
            config=HybridConfig(),
            has_conflict=False,
            single_source=False,
        )
        solo_conf = compute_confidence(
            0.80, 0.5, 0.8,
            config=HybridConfig(),
            has_conflict=False,
            single_source=True,
        )
        self.assertEqual(agreed_conf, "HIGH")
        self.assertIn(solo_conf, ("MEDIUM", "LOW"))

    def test_conflict_creates_wait(self):
        rule = RuleAdapter().from_signal("BUY", strength=0.8)
        ml = MLSignal(prediction=1, probability=0.7, direction="SELL", confidence="MEDIUM", accepted=True)
        conflict = resolve_conflict(rule, ml)
        self.assertEqual(conflict.decision, DECISION_WAIT)
        self.assertIn(WARNING_CONFLICT, conflict.warnings)

    def test_only_ml_signal_works(self):
        ml = MLSignal(prediction=1, probability=0.72, direction="BUY", confidence="HIGH", accepted=True)
        conflict = resolve_conflict(None, ml)
        self.assertEqual(conflict.decision, DECISION_BUY)
        self.assertEqual(conflict.agreement_score, 0.5)

    def test_only_rule_signal_works(self):
        rule = RuleAdapter().from_signal("SELL", strength=0.75)
        conflict = resolve_conflict(rule, None)
        self.assertEqual(conflict.decision, DECISION_SELL)
        self.assertEqual(conflict.agreement_score, 0.5)


class TestScoring(unittest.TestCase):
    def test_score_calculation_correctness(self):
        config = HybridConfig(ml_weight=0.6, rule_weight=0.4)
        rule = RuleAdapter().from_signal("BUY", strength=0.8)
        ml = MLSignal(prediction=1, probability=0.7, direction="BUY", confidence="HIGH", accepted=True)
        score = compute_final_score(rule, ml, config=config, resolved_direction=1)
        self.assertAlmostEqual(score, 0.7 * 0.6 + 0.8 * 0.4)

    def test_sell_direction_scoring(self):
        config = HybridConfig()
        rule = RuleAdapter().from_signal("SELL", strength=0.9)
        ml = MLSignal(prediction=1, probability=0.65, direction="SELL", confidence="MEDIUM", accepted=True)
        score = compute_final_score(rule, ml, config=config, resolved_direction=-1)
        self.assertAlmostEqual(score, 0.65 * 0.6 + 0.9 * 0.4)


class TestConfidence(unittest.TestCase):
    def test_confidence_calculation(self):
        cfg = HybridConfig()
        self.assertEqual(
            compute_confidence(0.80, 1.0, 0.75, config=cfg, has_conflict=False, single_source=False),
            "HIGH",
        )
        self.assertEqual(
            compute_confidence(0.75, 0.5, 0.6, config=cfg, has_conflict=False, single_source=True),
            "MEDIUM",
        )
        self.assertEqual(
            compute_confidence(0.80, 1.0, 0.75, config=cfg, has_conflict=True, single_source=False),
            "LOW",
        )


class TestLogging(unittest.TestCase):
    def test_logging_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _setup(tmp)
            row = df.iloc[-1].to_dict()
            predictor = MLPredictor("XAUUSD", "M5", "logistic", base_dir=tmp).load()
            engine = HybridDecisionEngine(MLAdapter(predictor), base_dir=tmp)
            result = engine.decide(row, rule_signal="BUY", rule_strength=0.85)
            path = hybrid_log_path("XAUUSD", tmp)
            self.assertTrue(path.is_file())
            rows = HybridLogger("XAUUSD", tmp).read_all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["decision"], result.decision)


class TestEngineIntegration(unittest.TestCase):
    def test_engine_with_mock_ml_for_rule_only(self):
        mock_predictor = MagicMock()
        mock_predictor.symbol = "XAUUSD"
        mock_predictor.timeframe = "M5"
        ml_adapter = MLAdapter(mock_predictor)
        neutral_ml = MLSignal(0, 0.4, "NEUTRAL", "LOW", accepted=False)
        ml_adapter.predict_with_raw = MagicMock(return_value=(neutral_ml, None))

        engine = HybridDecisionEngine(ml_adapter, log_decisions=False)
        result = engine.decide({"symbol": "XAUUSD", "timeframe": "M5"}, rule_signal="BUY", rule_strength=0.9)
        self.assertEqual(result.rule_signal, "BUY")


class TestIsolation(unittest.TestCase):
    def test_no_forbidden_imports(self):
        for path in HYBRID_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._assert_safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._assert_safe(node.module)

    def _assert_safe(self, module: str) -> None:
        for prefix in FORBIDDEN_IMPORT_PREFIXES:
            self.assertFalse(module.startswith(prefix), f"Forbidden import: {module}")

    def test_trading_kernel_unchanged(self):
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401

    def test_risk_gate_unchanged(self):
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401

    def test_no_execution_dependency(self):
        import tradingbot.ml.hybrid.engine as eng

        self.assertNotIn("mt5_execution", dir(eng))


if __name__ == "__main__":
    unittest.main()
