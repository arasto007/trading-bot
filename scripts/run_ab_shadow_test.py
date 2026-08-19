#!/usr/bin/env python3
"""Run A/B shadow test — rule vs hybrid (no live trading)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.abtest.report import ABReportGenerator, winner_display
from tradingbot.ml.abtest.schema import STATUS_INSUFFICIENT, WINNER_HYBRID, WINNER_RULE
from tradingbot.ml.memory.store import DecisionMemoryStore


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B shadow test: rule vs hybrid")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--min-samples", type=int, default=100)
    args = parser.parse_args()

    store = DecisionMemoryStore(args.symbol)
    report = ABReportGenerator(min_samples=args.min_samples).run_from_store(
        store,
        timeframe=args.timeframe,
    )

    winner = report.get("winner", "")
    if report.get("status") == STATUS_INSUFFICIENT:
        winner_label = "INSUFFICIENT_DATA"
    elif winner == WINNER_HYBRID:
        winner_label = "HYBRID"
    elif winner == WINNER_RULE:
        winner_label = "RULE"
    else:
        winner_label = winner_display(winner)

    print("A/B SHADOW TEST")
    print()
    print(f"Samples:\n{report.get('sample_size', 0)}")
    print()
    print(f"Rule Expected R:\n{report.get('rule_expected_R', 0.0):.2f}")
    print()
    print(f"Hybrid Expected R:\n{report.get('hybrid_expected_R', 0.0):.2f}")
    print()
    print(f"Winner:\n{winner_label}")
    print()
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
