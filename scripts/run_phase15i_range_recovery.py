#!/usr/bin/env python3
"""Phase 15I — range engine recovery CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase15i.orchestrator import run_phase15i_recovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 15I range engine recovery")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stride", type=int, default=15)
    parser.add_argument("--warmup", type=int, default=350)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    result = run_phase15i_recovery(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        stride=args.stride,
        warmup=args.warmup,
        base_dir=args.base_dir,
    )
    print(result.status)
    print(result.recommendation)
    print(f"root_cause: {result.root_cause}")
    print(f"reports: {result.reports_dir}")
    return 0 if result.recommendation == "READY_FOR_PHASE15J" else 1


if __name__ == "__main__":
    raise SystemExit(main())
