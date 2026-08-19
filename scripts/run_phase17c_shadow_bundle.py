#!/usr/bin/env python3
"""Phase 17C — shadow bundle validation (research only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase17c.config import DEFAULT_STRIDE, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME
from tradingbot.ml.research.phase17c.orchestrator import run_phase17c_validation


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 17C shadow bundle validation")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase17c_validation(
        symbol=args.symbol,
        timeframe=args.timeframe,
        stride=args.stride,
        base_dir=args.base_dir,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "checks": result["final_report"].get("checks"),
        "summary": result["final_report"].get("summary"),
    }, indent=2))
    return 0 if result["verdict"] != "REJECT_CANDIDATE" else 1


if __name__ == "__main__":
    sys.exit(main())
