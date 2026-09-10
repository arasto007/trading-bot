#!/usr/bin/env python3
"""Phase 18A — live shadow validation (no production impact, zero live orders)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase18a.config import (
    DEFAULT_DAYS,
    DEFAULT_STRIDE,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
)
from tradingbot.ml.research.phase18a.orchestrator import run_phase18a_shadow_validation


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 18A live shadow validation")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--base-dir", default=None)
    p.add_argument("--skip-stride1", action="store_true", help="Skip stride=1 stability pass")
    args = p.parse_args(argv)

    result = run_phase18a_shadow_validation(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        stride=args.stride,
        base_dir=args.base_dir,
        run_stride1=not args.skip_stride1,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "checks": result["checks"],
        "metrics": result["final_report"].get("metrics"),
    }, indent=2))
    return 0 if result["verdict"] == "READY_FOR_CONTROLLED_LIVE" else 1


if __name__ == "__main__":
    sys.exit(main())
