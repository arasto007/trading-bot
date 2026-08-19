"""Phase 14.3 — trade quality intelligence tests."""

from __future__ import annotations

import ast
import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase9_9_model_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.confidence_engine.validator import CalibratedDecision
from tradingbot.ml.decision_engine.decision_types import EngineSignal, FinalDecision, MarketContext
from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID, TREND_MODEL_ID
from tradingbot.ml.risk_intelligence.risk_types import RiskRecommendation
from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter, build_quality_context
from tradingbot.ml.trade_quality.liquidity_quality import classify_spread, liquidity_quality_score
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_policy import QUALITY_THRESHOLD, score_to_grade
from tradingbot.ml.trade_quality.quality_trace import build_quality_trace
from tradingbot.ml.trade_quality.quality_types import TradeQualityContext
from tradingbot.ml.trade_quality.regime_quality import regime_quality_score, VOL_REGIME_ENGINE
from tradingbot.ml.trade_quality.rr_quality import rr_quality_score
from tradingbot.ml.trade_quality.signal_quality import signal_quality_score
from tradingbot.ml.trade_quality.timing_quality import timing_quality_score
from tradingbot.ml.trade_quality.validator import EXPECTED_FINGERPRINT, run_quality_batch
from tradingbot.ml.trade_quality.volatility_quality import volatility_quality_score

PKG = ROOT / "tradingbot" / "ml" / "trade_quality"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _market(**kwargs) -> MarketContext:
    defaults = dict(
        symbol="XAUUSD",
        timeframe="M5",
        features={"spread_pips": 2.0, "adx": 30},
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


def _calibrated(**kwargs) -> CalibratedDecision:
    action = str(kwargs.get("action", "BUY"))
    conf = float(kwargs.get("confidence", 0.82))
    engine = kwargs.get("engine", TREND_MODEL_ID)
    regime = str(kwargs.get("regime", "TREND"))
    decision = FinalDecision(
        action=action,  # type: ignore[arg-type]
        engine=engine,
        confidence=conf,
        regime=regime,
        timestamp=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
        explanation=["test"],
        metadata={"raw_engine_signal": action},
    )
    return CalibratedDecision(
        decision=decision,
        raw_confidence=MagicMock(),
        calibrated=MagicMock(),
        final_action=action,
        final_confidence=conf,
    )


def _risk(**kwargs) -> RiskRecommendation:
    return RiskRecommendation(
        allowed=kwargs.get("allowed", True),
        risk_percent=kwargs.get("risk_percent", 0.30),
        multiplier=1.2,
        confidence_factor=1.0,
        regime_factor=1.1,
        volatility_factor=1.0,
        session_factor=1.0,
        drawdown_factor=1.0,
        reason="test",
    )


def _qctx(**kwargs) -> TradeQualityContext:
    market = kwargs.pop("market", _market())
    calibrated = kwargs.pop("calibrated", _calibrated())
    risk = kwargs.pop("risk", _risk())
    return build_quality_context(market, calibrated, risk, rr_ratio=kwargs.pop("rr_ratio", 2.0))


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


class TestPhase143Quality(unittest.TestCase):
    def test_signal_below_55(self):
        s, _ = signal_quality_score(0.50)
        self.assertEqual(s, 0.0)

    def test_signal_band_65_75(self):
        s, _ = signal_quality_score(0.70)
        self.assertEqual(s, 0.7)

    def test_signal_high(self):
        s, _ = signal_quality_score(0.90)
        self.assertEqual(s, 1.0)

    def test_trend_engine_in_trend(self):
        s, _ = regime_quality_score(TREND_MODEL_ID, "TREND")
        self.assertEqual(s, 1.0)

    def test_trend_v41_alias_in_trend(self):
        s, _ = regime_quality_score("trend_rf_v41", "TREND")
        self.assertEqual(s, 1.0)

    def test_trend_v41_alias_in_range(self):
        s, _ = regime_quality_score("trend_rf_v41", "RANGE")
        self.assertEqual(s, 0.4)

    def test_trend_engine_in_range(self):
        s, _ = regime_quality_score(TREND_MODEL_ID, "RANGE")
        self.assertEqual(s, 0.4)

    def test_range_engine_in_trend(self):
        s, _ = regime_quality_score(RANGE_MODEL_ID, "TREND")
        self.assertEqual(s, 0.5)

    def test_high_vol_regime_zero(self):
        s, _ = regime_quality_score(TREND_MODEL_ID, "HIGH_VOLATILITY")
        self.assertEqual(s, 0.0)

    def test_rr_below_15(self):
        s, _ = rr_quality_score(1.2)
        self.assertEqual(s, 0.0)

    def test_rr_at_2(self):
        s, _ = rr_quality_score(2.0)
        self.assertEqual(s, 1.0)

    def test_rr_vol_regime_0_8_allowed(self):
        s, _ = rr_quality_score(0.8, engine_id=VOL_REGIME_ENGINE)
        self.assertGreaterEqual(s, 0.85)

    def test_rr_vol_regime_1_2_band(self):
        s, _ = rr_quality_score(1.2, engine_id=VOL_REGIME_ENGINE)
        self.assertGreaterEqual(s, 0.90)

    def test_rr_vol_regime_below_floor_blocked(self):
        s, _ = rr_quality_score(0.5, engine_id=VOL_REGIME_ENGINE)
        self.assertEqual(s, 0.0)

    def test_rr_0_8_trend_engine_still_blocked(self):
        s, _ = rr_quality_score(0.8, engine_id="trend_rf_v40")
        self.assertEqual(s, 0.0)

    def test_rr_2_5_unchanged_all_engines(self):
        for engine in (None, "trend_rf_v40", "trend_rf_v41", VOL_REGIME_ENGINE):
            s, _ = rr_quality_score(2.5, engine_id=engine)
            self.assertEqual(s, 1.0)

    def test_vol_regime_engine_in_trend(self):
        s, _ = regime_quality_score(VOL_REGIME_ENGINE, "TREND")
        self.assertEqual(s, 1.0)

    def test_vol_regime_engine_high_vol_zero(self):
        s, _ = regime_quality_score(VOL_REGIME_ENGINE, "HIGH_VOLATILITY")
        self.assertEqual(s, 0.0)

    def test_atr_optimal_band(self):
        s, _ = volatility_quality_score(40.0)
        self.assertEqual(s, 1.0)

    def test_atr_high_band(self):
        s, _ = volatility_quality_score(85.0)
        self.assertEqual(s, 0.3)

    def test_atr_extreme_zero(self):
        s, _ = volatility_quality_score(95.0)
        self.assertEqual(s, 0.0)

    def test_spread_normal(self):
        s, _, cls = liquidity_quality_score(2.0)
        self.assertEqual(s, 1.0)
        self.assertEqual(cls, "normal")

    def test_spread_high_zero(self):
        s, _, _ = liquidity_quality_score(10.0)
        self.assertEqual(s, 0.0)

    def test_session_london(self):
        s, _ = timing_quality_score("london")
        self.assertEqual(s, 1.0)

    def test_session_off(self):
        s, _ = timing_quality_score("off_hours")
        self.assertEqual(s, 0.5)

    def test_quality_threshold_constant(self):
        self.assertEqual(QUALITY_THRESHOLD, 0.65)

    def test_grade_a(self):
        self.assertEqual(score_to_grade(0.90), "A")

    def test_grade_d(self):
        self.assertEqual(score_to_grade(0.50), "D")

    def test_good_setup_allowed(self):
        engine = TradeQualityEngine()
        score = engine.evaluate(_qctx())
        self.assertGreater(score.score, 0.0)
        self.assertTrue(score.allowed)

    def test_low_confidence_blocked(self):
        cal = _calibrated(confidence=0.50, action="BUY")
        score = TradeQualityEngine().evaluate(_qctx(calibrated=cal))
        self.assertFalse(score.allowed)

    def test_hold_action_blocked(self):
        cal = _calibrated(action="HOLD")
        score = TradeQualityEngine().evaluate(_qctx(calibrated=cal))
        self.assertFalse(score.allowed)

    def test_risk_blocked(self):
        score = TradeQualityEngine().evaluate(_qctx(risk=_risk(allowed=False, risk_percent=0)))
        self.assertFalse(score.allowed)

    def test_trace_generation(self):
        score = TradeQualityEngine().evaluate(_qctx())
        self.assertGreater(len(score.trace), 5)

    def test_build_quality_trace(self):
        ctx = _qctx()
        score = TradeQualityEngine().evaluate(ctx)
        trace = build_quality_trace(ctx, score)
        self.assertIn("quality", trace)

    def test_score_clamped(self):
        score = TradeQualityEngine().evaluate(_qctx())
        self.assertLessEqual(score.score, 1.0)
        self.assertGreaterEqual(score.score, 0.0)

    def test_classify_spread(self):
        self.assertEqual(classify_spread(2), "normal")
        self.assertEqual(classify_spread(6), "medium")

    def test_no_forbidden_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_fingerprint_unchanged_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            batch = run_quality_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
            self.assertTrue(batch["fingerprint_unchanged"])

    def test_phase99_checksum_unchanged(self):
        path = phase9_9_model_path(None)
        if not path.is_file():
            self.skipTest("phase9_9 missing")
        before = _sha256(path)
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_quality_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
        self.assertEqual(before, _sha256(path))

    def test_adapter_flow_mock(self):
        risk_adapter = MagicMock()
        risk_adapter.history = None
        cal = _calibrated()
        risk = _risk()
        risk_adapter.evaluate.return_value = (cal, risk)
        adapter = TradeQualityAdapter(risk_adapter)
        _, _, quality = adapter.evaluate(_market())
        self.assertIsNotNone(quality.to_dict())


if __name__ == "__main__":
    unittest.main()
