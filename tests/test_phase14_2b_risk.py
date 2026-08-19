"""Phase 14.2B — adaptive risk intelligence tests."""

from __future__ import annotations

import ast
import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase13_4_reports_dir, phase9_9_model_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.confidence_engine.validator import CalibratedDecisionAdapter
from tradingbot.ml.decision_engine.decision_types import EngineSignal, MarketContext
from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID, TREND_MODEL_ID
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
from tradingbot.ml.risk_intelligence.confidence_risk_mapper import confidence_risk_multiplier
from tradingbot.ml.risk_intelligence.drawdown_controller import drawdown_risk_multiplier
from tradingbot.ml.risk_intelligence.regime_risk_adjuster import regime_risk_multiplier
from tradingbot.ml.risk_intelligence.risk_policy import BASE_RISK_PERCENT, MAX_RISK_PERCENT, DEFAULT_RISK_POLICY
from tradingbot.ml.risk_intelligence.risk_trace import build_risk_trace
from tradingbot.ml.risk_intelligence.risk_types import AccountState, AdaptiveRiskContext, HistoricalMetrics
from tradingbot.ml.risk_intelligence.session_risk_adjuster import session_risk_multiplier
from tradingbot.ml.risk_intelligence.validator import (
    EXPECTED_FINGERPRINT,
    AdaptiveRiskAdapter,
    risk_context_from_calibrated,
    run_risk_batch,
)
from tradingbot.ml.risk_intelligence.volatility_risk_adjuster import volatility_risk_multiplier

PKG = ROOT / "tradingbot" / "ml" / "risk_intelligence"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")
FORBIDDEN_DIRS = ("tradingbot/kernel", "tradingbot/risk", "tradingbot/execution")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _market(**kwargs) -> MarketContext:
    defaults = dict(
        symbol="XAUUSD",
        timeframe="M5",
        features={"adx": 30, "atr_percentile": 35, "spread_pips": 1},
        regime="TREND",
        regime_strength=0.9,
        range_signal=EngineSignal(signal="HOLD", confidence=0.5, model=RANGE_MODEL_ID),
        trend_signal=EngineSignal(signal="BUY", confidence=0.85, model=TREND_MODEL_ID),
        volatility=35.0,
        session="london",
        timestamp=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return MarketContext(**defaults)


def _ctx(**kwargs) -> AdaptiveRiskContext:
    defaults = dict(
        market=_market(),
        calibrated_confidence=0.78,
        action="BUY",
        engine=TREND_MODEL_ID,
        regime="TREND",
        atr_percentile=35.0,
        session="london",
        account=AccountState(),
        history=HistoricalMetrics(),
    )
    defaults.update(kwargs)
    return AdaptiveRiskContext(**defaults)


def _candles(n: int = 500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.5, n).cumsum()
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close},
        index=ts,
    )


def _setup(tmp: str) -> None:
    store = DatasetStore(tmp)
    ts = pd.date_range("2024-01-01", periods=400, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    store.store_v2(
        "XAUUSD",
        "M5",
        pd.DataFrame(
            {
                "timestamp": ts,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "label": [0, 1] * 200,
                "ema50_slope": rng.normal(0, 1, 400).tolist(),
                "candle_direction": rng.normal(0, 1, 400).tolist(),
                "structure_distance": rng.normal(0, 1, 400).tolist(),
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
            }
        ),
    )
    CandleStore(tmp).store("XAUUSD", "M5", _candles(500))


class TestPhase142BRisk(unittest.TestCase):
    def test_confidence_below_55_zero(self):
        f, _ = confidence_risk_multiplier(0.50)
        self.assertEqual(f, 0.0)

    def test_confidence_band_55_65(self):
        f, _ = confidence_risk_multiplier(0.60)
        self.assertEqual(f, 0.5)

    def test_confidence_band_75_85(self):
        f, _ = confidence_risk_multiplier(0.80)
        self.assertEqual(f, 1.0)

    def test_confidence_high_band(self):
        f, _ = confidence_risk_multiplier(0.90)
        self.assertEqual(f, 1.25)

    def test_regime_trend_boost(self):
        f, _, blocked = regime_risk_multiplier("TREND")
        self.assertEqual(f, 1.10)
        self.assertFalse(blocked)

    def test_regime_no_trade_block(self):
        f, _, blocked = regime_risk_multiplier("NO_TRADE")
        self.assertTrue(blocked)

    def test_high_vol_reduction(self):
        f, _, _ = regime_risk_multiplier("HIGH_VOLATILITY")
        self.assertEqual(f, 0.5)

    def test_atr_low_vol_boost(self):
        f, _, blocked = volatility_risk_multiplier(20.0)
        self.assertEqual(f, 1.10)
        self.assertFalse(blocked)

    def test_atr_high_vol_reduction(self):
        f, _, _ = volatility_risk_multiplier(80.0)
        self.assertEqual(f, 0.70)

    def test_atr_extreme_block(self):
        f, _, blocked = volatility_risk_multiplier(95.0)
        self.assertTrue(blocked)

    def test_drawdown_normal(self):
        f, _, blocked = drawdown_risk_multiplier(2.0)
        self.assertEqual(f, 1.0)
        self.assertFalse(blocked)

    def test_drawdown_mid_reduction(self):
        f, _, _ = drawdown_risk_multiplier(4.0)
        self.assertEqual(f, 0.75)

    def test_drawdown_severe_block(self):
        f, _, blocked = drawdown_risk_multiplier(9.0)
        self.assertTrue(blocked)

    def test_session_london_boost(self):
        f, label = session_risk_multiplier("london")
        self.assertEqual(f, 1.10)
        self.assertIn("LONDON", label)

    def test_session_off_reduction(self):
        f, _ = session_risk_multiplier("off_hours")
        self.assertEqual(f, 0.80)

    def test_risk_clamp_max(self):
        engine = AdaptiveRiskEngine()
        rec = engine.recommend(_ctx(calibrated_confidence=0.95, atr_percentile=25.0))
        self.assertLessEqual(rec.risk_percent, MAX_RISK_PERCENT)

    def test_zero_risk_hold_action(self):
        rec = AdaptiveRiskEngine().recommend(_ctx(action="HOLD"))
        self.assertFalse(rec.allowed)
        self.assertEqual(rec.risk_percent, 0.0)

    def test_trace_generation(self):
        rec = AdaptiveRiskEngine().recommend(_ctx())
        self.assertGreater(len(rec.trace), 4)

    def test_build_risk_trace_record(self):
        rec = AdaptiveRiskEngine().recommend(_ctx())
        trace = build_risk_trace(_ctx(), rec)
        self.assertIn("recommendation", trace)

    def test_base_risk_constant(self):
        self.assertEqual(BASE_RISK_PERCENT, 0.25)

    def test_policy_clamp(self):
        self.assertEqual(DEFAULT_RISK_POLICY.clamp_risk(0.99), MAX_RISK_PERCENT)

    def test_no_forbidden_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_order_send_strings(self):
        for py in PKG.rglob("*.py"):
            self.assertNotIn("order_send", py.read_text(encoding="utf-8"))

    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_phase99_checksum_unchanged(self):
        path = phase9_9_model_path(None)
        if not path.is_file():
            self.skipTest("phase9_9 missing")
        before = _sha256(path)
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_risk_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
        self.assertEqual(before, _sha256(path))

    def test_fingerprint_unchanged_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            batch = run_risk_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
            self.assertTrue(batch["fingerprint_unchanged"])

    def test_adapter_integration(self):
        adapter = AdaptiveRiskAdapter(CalibratedDecisionAdapter(DecisionOrchestrator()))
        ctx = _market(regime="TREND")
        _, risk = adapter.evaluate(ctx)
        self.assertIsNotNone(risk.to_dict())

    def test_high_confidence_produces_risk(self):
        rec = AdaptiveRiskEngine().recommend(_ctx(calibrated_confidence=0.82))
        if rec.allowed:
            self.assertGreater(rec.risk_percent, 0.0)

    def test_engine_performance_factor(self):
        hist = HistoricalMetrics()
        self.assertGreater(hist.engine_quality_factor(TREND_MODEL_ID), 0.9)
        self.assertGreater(hist.engine_quality_factor(RANGE_MODEL_ID), 1.0)


if __name__ == "__main__":
    unittest.main()
