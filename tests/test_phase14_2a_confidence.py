"""Phase 14.2A — confidence calibration tests."""

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
from tradingbot.ml.confidence_engine.calibration_policy import (
    DEFAULT_CALIBRATION_POLICY,
    MAX_CONFIDENCE,
    MIN_CALIBRATED_CONFIDENCE,
    MIN_RAW_CONFIDENCE,
)
from tradingbot.ml.confidence_engine.calibration_trace import confidence_band
from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
from tradingbot.ml.confidence_engine.calibrator import ConfidenceCalibrator, clamp
from tradingbot.ml.confidence_engine.engine_calibrator import (
    RANGE_MODEL_ID,
    TREND_MODEL_ID,
    engine_calibration_factor,
)
from tradingbot.ml.confidence_engine.regime_calibrator import RegimeCalibrator
from tradingbot.ml.confidence_engine.session_adjuster import SessionAdjuster
from tradingbot.ml.confidence_engine.validator import (
    EXPECTED_FINGERPRINT,
    CalibratedDecisionAdapter,
    run_calibration_batch,
    validate_artifact_checksums,
)
from tradingbot.ml.confidence_engine.volatility_adjuster import VolatilityAdjuster, classify_volatility
from tradingbot.ml.decision_engine.decision_types import EngineSignal, FinalDecision, MarketContext
from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID as DE_RANGE
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator

PKG = ROOT / "tradingbot" / "ml" / "confidence_engine"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw(
    *,
    raw_value: float = 0.22,
    engine: str = TREND_MODEL_ID,
    regime: str = "TREND",
    session: str = "new_york",
    volatility: float = 45.0,
) -> RawConfidence:
    return RawConfidence(
        raw_value=raw_value,
        engine=engine,
        regime=regime,
        model_probability=0.75,
        regime_strength=0.85,
        market_quality=0.80,
        session=session,
        volatility=volatility,
        volatility_state=classify_volatility(volatility),
        engine_signal="BUY",
    )


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


class TestPhase142AConfidence(unittest.TestCase):
    def test_raw_confidence_accepted(self):
        cal = ConfidenceCalibrator()
        out = cal.calibrate(_raw(raw_value=0.22))
        self.assertGreater(out.calibrated_value, 0.22)

    def test_calibration_deterministic(self):
        cal = ConfidenceCalibrator()
        raw = _raw()
        self.assertEqual(cal.calibrate(raw).to_dict(), cal.calibrate(raw).to_dict())

    def test_range_adjustment(self):
        factor, _ = engine_calibration_factor(engine=RANGE_MODEL_ID, regime="RANGE", regime_strength=0.8)
        self.assertGreaterEqual(factor, 0.8)
        self.assertLessEqual(factor, 1.3)

    def test_trend_adjustment(self):
        factor, label = engine_calibration_factor(engine=TREND_MODEL_ID, regime="TREND", regime_strength=0.9)
        self.assertGreaterEqual(factor, 1.0)
        self.assertLessEqual(factor, 1.5)
        self.assertIn("validated", label)

    def test_high_vol_reduction(self):
        reg = RegimeCalibrator()
        factor, label = reg.factor("HIGH_VOLATILITY")
        self.assertEqual(factor, 0.5)
        self.assertIn("HIGH_VOL", label)

    def test_no_trade_zero(self):
        cal = ConfidenceCalibrator()
        out = cal.calibrate(_raw(regime="NO_TRADE", engine=None, raw_value=0.5))
        self.assertEqual(out.calibrated_value, 0.0)
        self.assertEqual(out.confidence_band, "ZERO")

    def test_session_adjustment(self):
        adj = SessionAdjuster()
        asia, _, name = adj.factor("asia")
        off, _, _ = adj.factor("off_hours")
        self.assertEqual(name, "ASIA")
        self.assertGreater(asia, off)

    def test_volatility_adjustment(self):
        vol = VolatilityAdjuster()
        low, _, state = vol.factor(20.0)
        high, _, state2 = vol.factor(80.0)
        self.assertEqual(state, "LOW_VOL")
        self.assertEqual(state2, "HIGH_VOL")
        self.assertGreater(low, high)

    def test_extreme_volatility_reject(self):
        cal = ConfidenceCalibrator()
        out = cal.calibrate(_raw(volatility=96.0))
        self.assertEqual(out.calibrated_value, 0.0)

    def test_confidence_clamp(self):
        self.assertEqual(clamp(1.5), MAX_CONFIDENCE)
        self.assertEqual(clamp(-0.1), 0.0)

    def test_trace_generation(self):
        cal = ConfidenceCalibrator()
        out = cal.calibrate(_raw())
        self.assertGreater(len(out.trace), 3)
        self.assertGreater(len(out.adjustments), 0)

    def test_policy_constants(self):
        self.assertEqual(MIN_RAW_CONFIDENCE, 0.10)
        self.assertEqual(MIN_CALIBRATED_CONFIDENCE, 0.55)
        self.assertEqual(MAX_CONFIDENCE, 1.0)

    def test_confidence_band_labels(self):
        self.assertEqual(confidence_band(0.0), "ZERO")
        self.assertEqual(confidence_band(0.7), "HIGH")

    def test_no_execution_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_phase99_checksum_unchanged(self):
        path = phase9_9_model_path(None)
        if not path.is_file():
            self.skipTest("phase9_9 model missing")
        before = _sha256(path)
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_calibration_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
        self.assertEqual(before, _sha256(path))

    def test_trend_rf_checksum_unchanged(self):
        path = phase13_4_reports_dir(None) / "trend_ml_best_model.json"
        if not path.is_file():
            self.skipTest("trend metadata missing")
        before = _sha256(path)
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_calibration_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
        self.assertEqual(before, _sha256(path))

    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_adapter_integration(self):
        ctx = MarketContext(
            symbol="XAUUSD",
            timeframe="M5",
            features={"adx": 30, "ema50_slope": 0.2, "atr_percentile": 45, "spread_pips": 1},
            regime="TREND",
            regime_strength=0.9,
            range_signal=EngineSignal(signal="HOLD", confidence=0.5, model=DE_RANGE),
            trend_signal=EngineSignal(signal="BUY", confidence=0.85, model=TREND_MODEL_ID),
            volatility=45.0,
            session="new_york",
            timestamp=datetime(2024, 6, 1, 14, 0, tzinfo=timezone.utc),
        )
        adapter = CalibratedDecisionAdapter(DecisionOrchestrator())
        result = adapter.decide(ctx)
        self.assertIn("calibrated_confidence", result.to_dict())
        self.assertGreater(result.final_confidence, 0.0)

    def test_fingerprint_unchanged_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            batch = run_calibration_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
            self.assertTrue(batch["fingerprint_unchanged"])

    def test_artifact_validation_helper(self):
        info = validate_artifact_checksums()
        self.assertIn("phase9_9_model", info)

    def test_calibrated_never_exceeds_one(self):
        cal = ConfidenceCalibrator()
        out = cal.calibrate(_raw(raw_value=0.95, regime="TREND"))
        self.assertLessEqual(out.calibrated_value, 1.0)

    def test_raw_below_minimum_zeroes(self):
        cal = ConfidenceCalibrator()
        out = cal.calibrate(_raw(raw_value=0.05))
        self.assertEqual(out.calibrated_value, 0.0)

    def test_policy_gate(self):
        self.assertTrue(DEFAULT_CALIBRATION_POLICY.passes_gate(0.60))
        self.assertFalse(DEFAULT_CALIBRATION_POLICY.passes_gate(0.40))


if __name__ == "__main__":
    unittest.main()
