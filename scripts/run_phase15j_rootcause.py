#!/usr/bin/env python3
"""Phase 15J — trend engine root cause trace CLI (read-only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase15j.orchestrator import run_phase15j_rootcause


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 15J trend root cause trace (read-only)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stride", type=int, default=15)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    result = run_phase15j_rootcause(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        stride=args.stride,
        base_dir=args.base_dir,
    )
    print(result.status)
    print(f"root_cause: {result.root_cause}")
    print(f"primary_stop_stage: {result.primary_stop_stage}")
    print(f"phase15k: {result.phase15k_focus}")
    print(f"reports: {result.reports_dir}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
