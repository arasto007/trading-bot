#!/usr/bin/env python3
"""Run deployment readiness check — Phase 6.4 evaluation only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.deployment.live_readiness_engine import LiveReadinessEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Deployment readiness evaluation — no live trading")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    report = LiveReadinessEngine().evaluate_readiness(args.symbol, args.timeframe)

    print("DEPLOYMENT STATUS")
    print()
    print(f"State:\n{report.status}")
    print()
    print(f"Score:\n{report.score:.2f}")
    print()
    print("Risk Flags:")
    if report.risk_flags:
        for flag in report.risk_flags:
            print(f"- {flag}")
    else:
        print("- None")
    print()
    print(f"Recommendation:\n{report.recommendation_text}")
    print()
    print("Execution:\nDISABLED")
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
