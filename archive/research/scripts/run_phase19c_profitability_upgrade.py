#!/usr/bin/env python3
"""Phase 19C — safe profitability upgrade validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase19c.config import DEFAULT_SYMBOL, DEFAULT_STRIDE, DEFAULT_TIMEFRAME
from tradingbot.ml.phase19c.orchestrator import run_phase19c_upgrade


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 19C safe profitability upgrade")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase19c_upgrade(
        symbol=args.symbol,
        timeframe=args.timeframe,
        base_dir=args.base_dir,
        stride=args.stride,
    )
    comp = result["comparison"]
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "comparison_3y": comp,
        "rollback_passed": result["rollback"].get("passed"),
    }, indent=2))
    return 0 if result["verdict"] == "IMPROVEMENT_ACCEPTED" else 1


if __name__ == "__main__":
    sys.exit(main())
