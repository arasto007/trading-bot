#!/usr/bin/env python3
"""Phase 15D — shadow mode live safety validation CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.live_validation.orchestrator import run_phase15d_shadow


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 15D shadow mode validation")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stride", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=350)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    result = run_phase15d_shadow(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        base_dir=args.base_dir,
        stride=args.stride,
        warmup=args.warmup,
        legacy_config={"BASE_DIR": args.base_dir or str(ROOT)},
    )

    print(result.status)
    print(result.recommendation)
    print(f"reports: {result.reports_dir}")
    if result.validation.blockers:
        for b in result.validation.blockers:
            print(f"  blocker: {b['id']} — {b['detail']}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
