#!/usr/bin/env python3
"""Phase 16C — TREND engine throughput root analysis (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase16c.config import (
    DEFAULT_DAYS,
    DEFAULT_STRIDE,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
)
from tradingbot.ml.research.phase16c.orchestrator import run_phase16c_analysis


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 16C TREND throughput forensic analysis")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase16c_analysis(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        stride=args.stride,
        base_dir=args.base_dir,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "recommended_next_phase": result["final_report"].get("recommended_next_phase"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
