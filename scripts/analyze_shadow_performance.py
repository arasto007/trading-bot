#!/usr/bin/env python3
"""Analyze shadow ML/hybrid performance — Phase 5.2 (offline only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import candle_path
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.memory.evaluator import ShadowDecisionEvaluator
from tradingbot.ml.memory.reports import ShadowReportGenerator
from tradingbot.ml.memory.store import DecisionMemoryStore


def _load_candles(symbol: str, timeframe: str) -> "object":
    store = CandleStore()
    df = store.load(symbol, timeframe)
    if df is None or df.empty:
        path = candle_path(symbol, timeframe)
        raise FileNotFoundError(f"No candle data for outcome evaluation: {path}")
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow performance analysis (no live trading)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--skip-evaluate", action="store_true", help="Only analyze stored outcomes")
    args = parser.parse_args()

    memory = DecisionMemoryStore(args.symbol)
    if not args.skip_evaluate:
        try:
            candles = _load_candles(args.symbol, args.timeframe)
            ShadowDecisionEvaluator(memory).evaluate_all(candles)
        except FileNotFoundError as exc:
            print(f"Warning: {exc}")

    report = ShadowReportGenerator().generate_from_store(memory, timeframe=args.timeframe)
    perf = report["shadow_performance"]
    cal = report["confidence_calibration"]

    print("SHADOW PERFORMANCE REPORT")
    print()
    print(f"Predictions:\n{perf.get('predictions', 0)}")
    print()
    print(f"Win Rate:\n{perf.get('win_rate', 0.0) * 100:.0f}%")
    print()
    print(f"Expected R:\n{perf.get('expected_R', 0.0):.2f}")
    print()
    print(f"Best Session:\n{perf.get('best_session') or 'N/A'}")
    print()
    print(f"Worst Regime:\n{perf.get('worst_regime') or 'N/A'}")
    print()
    print(f"Confidence Calibration:\n{cal.get('status', 'N/A')}")
    print()
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
