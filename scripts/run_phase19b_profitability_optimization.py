#!/usr/bin/env python3
"""Phase 19B — profitability optimization (research only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase19b.config import DEFAULT_STRIDE, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME
from tradingbot.ml.research.phase19b.orchestrator import run_phase19b_optimization


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 19B research profitability optimization")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase19b_optimization(
        symbol=args.symbol,
        timeframe=args.timeframe,
        base_dir=args.base_dir,
        stride=args.stride,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "top_improvements": result["top_improvements"],
    }, indent=2))
    return 0 if result["verdict"] == "SAFE_IMPROVEMENTS_AVAILABLE" else 1


if __name__ == "__main__":
    sys.exit(main())
