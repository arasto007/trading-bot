#!/usr/bin/env python3
"""Run ML performance profiling — Phase 7.2 benchmarking only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.performance.report import PerformanceReportGenerator


def main() -> int:
    parser = argparse.ArgumentParser(description="ML shadow performance profiling")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--feature-rows", type=int, default=1000)
    args = parser.parse_args()

    report = PerformanceReportGenerator(
        symbol=args.symbol,
        timeframe=args.timeframe,
        feature_rows=args.feature_rows,
    ).generate()

    summary = {
        "system": report.get("system"),
        "model": "shadow_pipeline",
        "feature_status": "OK" if report.get("feature_build_ms", 0) < 5000 else "SLOW",
        "monitoring": "OK" if report.get("monitoring_ms", 0) < 500 else "SLOW",
        "gate": "N/A",
        "live_enabled": False,
        "average_prediction_ms": report.get("average_prediction_ms"),
        "feature_build_ms": report.get("feature_build_ms"),
        "orchestrator_ms": report.get("orchestrator_ms"),
        "memory_usage_mb": report.get("memory_usage_mb"),
        "recommendations": report.get("recommendations", []),
    }
    print(json.dumps(summary, indent=2))
    print()
    print("Execution:\nDISABLED")
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
