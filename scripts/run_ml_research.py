#!/usr/bin/env python3
"""Run ML research intelligence pipeline — Phase 7.3."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.reports import ResearchReportGenerator


def main() -> int:
    parser = argparse.ArgumentParser(description="ML research intelligence — offline analysis only")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    report = ResearchReportGenerator().run(args.symbol, args.timeframe)
    print(json.dumps(report.get("summary", report), indent=2))
    print()
    print("Execution:\nDISABLED")
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
