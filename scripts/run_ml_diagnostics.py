#!/usr/bin/env python3
"""Run ML system diagnostics — Phase 7.0."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.infrastructure.diagnostics.diagnostic_report import DiagnosticReportGenerator


def main() -> int:
    parser = argparse.ArgumentParser(description="ML shadow ecosystem diagnostics")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    report = DiagnosticReportGenerator().generate(args.symbol, args.timeframe)
    summary = {
        "system": report.get("system"),
        "model": report.get("model"),
        "feature_status": report.get("feature_status"),
        "monitoring": report.get("monitoring"),
        "gate": report.get("gate"),
        "live_enabled": report.get("live_enabled"),
    }
    print(json.dumps(summary, indent=2))
    print()
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
