#!/usr/bin/env python3
"""Phase 12 — pre-live health check CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.live_pilot.config import PilotConfig
from tradingbot.ml.live_pilot.health_check import run_health_check


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 12 live pilot health check")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--run", default="v1")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--skip-preflight", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = PilotConfig(symbol=args.symbol, timeframe=args.timeframe, run_id=args.run)
    report = run_health_check(
        config=config,
        base_dir=args.base_dir,
        run_preflight=not args.skip_preflight,
    )
    print(json.dumps(report, indent=2))
    return 0 if report.get("health_check") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
