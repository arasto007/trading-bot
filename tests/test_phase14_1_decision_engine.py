"""Phase 14.1 — decision engine tests."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase9_9_model_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine, compute_regime_strength
from tradingbot.ml.decision_engine.decision_policy import DEFAULT_POLICY, RANGE_MODEL_ID, TREND_MODEL_ID
from tradingbot.ml.decision_engine.decision_trace import build_trace
from tradingbot.ml.decision_engine.decision_types import EngineSignal, MarketContext
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.strategy_selector import select_engine
from tradingbot.ml.decision_engine.validation import (
    EXPECTED_FINGERPRINT,
    build_market_context,
    run_decision_batch,
    validate_routing,
)

PKG = ROOT / "tradingbot" / "ml" / "decision_engine"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")
KERNEL_DIR = ROOT / "tradingbot" / "kernel"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ctx(
    regime: str,
    *,
    range_sig: str = "HOLD",
    trend_sig: str = "HOLD",
    range_conf: float = 0.7,
    trend_conf: float = 0.8,
    regime_strength: float = 0.9,
) -> MarketContext:
    return MarketContext(
        symbol="XAUUSD",
        timeframe="M5",
        features={"adx": 28.0, "ema50_slope": 0.2, "atr_percentile": 45.0, "spread_pips": 1.0},
        regime=regime,
        regime_strength=regime_strength,
        range_signal=EngineSignal(signal=range_sig, confidence=range_conf, model=RANGE_MODEL_ID),  # type: ignore[arg-type]
        trend_signal=EngineSignal(signal=trend_sig, confidence=trend_conf, model=TREND_MODEL_ID),  # type: ignore[arg-type]
        volatility=45.0,
        session="london",
        timestamp=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
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


class TestPhase141DecisionEngine(unittest.TestCase):
    def test_regime_routing_table(self):
        routing = validate_routing()
        self.assertTrue(routing["passes"])
        self.assertEqual(select_engine("RANGE"), RANGE_MODEL_ID)
        from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
        self.assertEqual(select_engine("TREND"), resolve_active_trend_engine_id())

    def test_range_selects_phase99(self):
        orch = DecisionOrchestrator()
        ctx = _ctx("RANGE", range_sig="BUY", range_conf=0.85)
        d = orch.decide(ctx)
        self.assertEqual(d.engine, RANGE_MODEL_ID)

    def test_trend_selects_trend_engine(self):
        from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

        orch = DecisionOrchestrator()
        ctx = _ctx("TREND", trend_sig="SELL", trend_conf=0.82)
        d = orch.decide(ctx)
        self.assertEqual(d.engine, resolve_active_trend_engine_id())

    def test_high_vol_blocks(self):
        orch = DecisionOrchestrator()
        d = orch.decide(_ctx("HIGH_VOLATILITY", trend_sig="BUY", range_sig="BUY"))
        self.assertEqual(d.action, "HOLD")
        self.assertIsNone(d.engine)

    def test_no_trade_blocks(self):
        orch = DecisionOrchestrator()
        d = orch.decide(_ctx("NO_TRADE", trend_sig="SELL"))
        self.assertEqual(d.action, "HOLD")
        self.assertIsNone(d.engine)

    def test_confidence_calculation(self):
        engine = ConfidenceEngine()
        final = engine.compute(model_confidence=0.80, regime_strength=0.90, market_quality=0.85)
        self.assertAlmostEqual(final, 0.612, places=3)

    def test_threshold_rejection(self):
        orch = DecisionOrchestrator(policy=DEFAULT_POLICY)
        ctx = _ctx("TREND", trend_sig="BUY", trend_conf=0.50, regime_strength=0.5)
        d = orch.decide(ctx)
        self.assertEqual(d.action, "HOLD")

    def test_decision_trace_creation(self):
        ctx = _ctx("TREND", trend_sig="BUY", trend_conf=0.90)
        trace = build_trace(
            context=ctx,
            engine_id=TREND_MODEL_ID,
            model_confidence=0.90,
            final_confidence=0.70,
            raw_action="BUY",
            final_action="BUY",
            policy_threshold=0.55,
        )
        self.assertGreaterEqual(len(trace), 4)
        self.assertIn("Regime detected TREND", trace[0])

    def test_deterministic_output(self):
        orch = DecisionOrchestrator()
        ctx = _ctx("RANGE", range_sig="SELL", range_conf=0.88)
        a = orch.decide(ctx)
        b = orch.decide(ctx)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_no_execution_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_kernel_modification(self):
        if KERNEL_DIR.is_dir():
            mtimes = {p: p.stat().st_mtime for p in KERNEL_DIR.rglob("*.py")}
            self.assertGreater(len(mtimes), 0)

    def test_phase99_checksum_unchanged_after_batch(self):
        path = phase9_9_model_path(None)
        if not path.is_file():
            self.skipTest("Phase 9.9 model not present")
        before = _sha256(path)
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_decision_batch(symbol="XAUUSD", timeframe="M5", days=5, base_dir=tmp, seed=42)
        after = _sha256(path)
        self.assertEqual(before, after)

    def test_unified_decision_object_fields(self):
        orch = DecisionOrchestrator()
        d = orch.decide(_ctx("TREND", trend_sig="BUY", trend_conf=0.90))
        payload = d.to_dict()
        for key in ("action", "selected_engine", "regime", "confidence", "reason", "trace"):
            self.assertIn(key, payload)

    def test_explanation_present(self):
        orch = DecisionOrchestrator()
        d = orch.decide(_ctx("TREND", trend_sig="BUY", trend_conf=0.90))
        self.assertGreater(len(d.explanation), 0)
        self.assertGreater(len(d.trace), 0)

    def test_regime_strength_bounded(self):
        strength = compute_regime_strength({"adx": 30, "ema50_slope": 0.2}, "TREND")
        self.assertGreaterEqual(strength, 0.0)
        self.assertLessEqual(strength, 1.0)

    def test_expected_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_orchestrator_batch_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            batch = run_decision_batch(symbol="XAUUSD", timeframe="M5", days=3, base_dir=tmp, seed=42)
            self.assertTrue(batch["fingerprint_unchanged"])
            self.assertGreater(batch["bars_processed"], 0)


if __name__ == "__main__":
    unittest.main()
