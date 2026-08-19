#!/usr/bin/env python3
"""Run hybrid ML + rule shadow mode — Phase 5.1 (live trading unchanged)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision.predictor import MLPredictor
from tradingbot.ml.hybrid.engine import HybridDecisionEngine
from tradingbot.ml.hybrid.ml_adapter import MLAdapter
from tradingbot.ml.models.training import MODEL_CHOICES


def _latest_row(symbol: str, timeframe: str) -> dict:
    store = DatasetStore()
    df = store.load(symbol, timeframe)
    if df is None or df.empty:
        raise FileNotFoundError(f"No dataset for {symbol} {timeframe}")
    return df.sort_values("timestamp").iloc[-1].to_dict()


def _infer_rule_signal(row: dict) -> str:
    """Derive mock rule signal from H4 bias when no live rule engine is connected."""
    bias = float(row.get("h4_trend_bias", 0.0))
    if bias > 0:
        return "BUY"
    if bias < 0:
        return "SELL"
    return "WAIT"


def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid shadow mode (recommendation only)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", required=True, choices=MODEL_CHOICES)
    parser.add_argument("--rule-signal", default=None, help="Override rule signal (BUY/SELL/WAIT)")
    args = parser.parse_args()

    row = _latest_row(args.symbol, args.timeframe)
    rule_signal = args.rule_signal or _infer_rule_signal(row)

    predictor = MLPredictor(args.symbol, args.timeframe, args.model).load()
    engine = HybridDecisionEngine(MLAdapter(predictor))
    result = engine.decide(row, rule_signal=rule_signal)

    agreement = "YES" if result.agreement_score >= 1.0 else "NO"
    ml_label = result.ml_direction if result.ml_prediction == 1 else "WAIT"

    print("HYBRID SHADOW MODE")
    print()
    print(f"Rule Signal:\n{result.rule_signal}")
    print()
    print(f"ML Prediction:\n{ml_label}")
    print()
    print(f"ML Probability:\n{result.ml_probability:.2f}")
    print()
    print(f"Agreement:\n{agreement}")
    print()
    print(f"Final Decision:\n{result.decision}")
    print()
    print(f"Confidence:\n{result.confidence}")
    print()
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
