#!/usr/bin/env python3
"""Phase 14.4 — signal optimization & opportunity recovery CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase14_4.orchestrator import run_phase14_4_optimizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.4 signal optimization")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    result = run_phase14_4_optimizer(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        base_dir=args.base_dir,
        quick=args.quick,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
