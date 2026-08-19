#!/usr/bin/env python3
"""Run ML shadow monitoring — Phase 6.1 (informational only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.monitoring.health import drift_severity_label
from tradingbot.ml.monitoring.reports import MonitoringReportGenerator


def main() -> int:
    parser = argparse.ArgumentParser(description="ML shadow monitoring report")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    store = DecisionMemoryStore(args.symbol)
    result = MonitoringReportGenerator().run(store, timeframe=args.timeframe, model_name=args.model)
    summary = result["summary"]
    dashboard = result["dashboard"]

    print("ML MONITORING REPORT")
    print()
    print(f"Model:\n{summary.get('model_name', 'unknown')}")
    print()
    print(f"Health:\n{summary.get('model_health', 'UNKNOWN')}")
    print()
    print(f"Expected R:\n{summary.get('expected_R', 0.0):.2f}")
    print()
    print(f"Hybrid Delta:\n{summary.get('hybrid_vs_rule_delta', 0.0):+.2f}")
    print()
    drift_score = float(summary.get("feature_drift_score", 0.0))
    print(f"Feature Drift:\n{drift_severity_label(drift_score)}")
    print()
    print(f"Alerts:\n{summary.get('alert_count', 0)}")
    print()
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
