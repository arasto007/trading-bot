#!/usr/bin/env python3
"""Phase 13.8 — trend recovery research CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase13_8.orchestrator import run_phase13_8_trend_recovery


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 13.8 trend recovery")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    result = run_phase13_8_trend_recovery(
        symbol=args.symbol,
        timeframe=args.timeframe,
        seed=args.seed,
        base_dir=args.base_dir,
        quick=args.quick,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
