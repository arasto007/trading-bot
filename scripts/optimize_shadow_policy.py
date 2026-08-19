#!/usr/bin/env python3
"""Optimize shadow ML+rule policy from memory — Phase 5.3 (recommendations only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.optimization.optimizer import ShadowPolicyOptimizer


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow policy optimization (no live trading)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--min-samples", type=int, default=5)
    args = parser.parse_args()

    store = DecisionMemoryStore(args.symbol)
    optimizer = ShadowPolicyOptimizer(min_samples=args.min_samples)
    report = optimizer.run_and_report(store, timeframe=args.timeframe)

    print("SHADOW OPTIMIZATION")
    print()
    print(f"Current Expected R:\n{report.get('expected_R_before', 0.0):.2f}")
    print()
    print(f"Optimized Expected R:\n{report.get('expected_R_after', 0.0):.2f}")
    print()
    print(f"Recommended Threshold:\n{report.get('best_threshold', 0.5):.2f}")
    print()
    print(f"Recommended ML Weight:\n{report.get('best_ml_weight', 0.6):.2f}")
    print()
    print(f"Status:\n{report.get('status', 'READY FOR REVIEW')}")
    print()
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
