#!/usr/bin/env python3
"""Run ML improvement recommendations — Phase 7.4."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.improvement.reports import ImprovementReportGenerator


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline ML improvement recommendations")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    report = ImprovementReportGenerator().run(args.symbol, args.timeframe)
    summary = {
        "top_improvements": len(report.get("top_improvements", [])),
        "experiments_queued": len(report.get("experiments_to_run", [])),
        "feature_suggestions": len(report.get("feature_suggestions", [])),
        "model_suggestions": len(report.get("model_suggestions", [])),
        "auto_apply": report.get("auto_apply", False),
        "live_enabled": report.get("live_enabled", False),
    }
    print(json.dumps(summary, indent=2))
    print()
    print("Top recommendations:")
    for item in report.get("top_improvements", [])[:3]:
        print(f"- {item.get('issue')}: {item.get('recommendation')} (confidence={item.get('confidence')})")
    print()
    print("Execution:\nDISABLED")
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
