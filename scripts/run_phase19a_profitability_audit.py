#!/usr/bin/env python3
"""Phase 19A — profitability audit (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase19a.config import DEFAULT_SYMBOL, DEFAULT_STRIDE, DEFAULT_TIMEFRAME
from tradingbot.ml.phase19a.orchestrator import run_phase19a_audit


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 19A profitability audit")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase19a_audit(
        symbol=args.symbol,
        timeframe=args.timeframe,
        base_dir=args.base_dir,
        stride=args.stride,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "overall_score": result["final_score"].get("overall_score"),
        "performance_3y": result["performance_summary"]["windows"].get("1095d", {}).get("performance"),
    }, indent=2))
    return 0 if result["verdict"] != "NOT_READY_FOR_REAL_CAPITAL" else 1


if __name__ == "__main__":
    sys.exit(main())
