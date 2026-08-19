#!/usr/bin/env python3
"""Phase 20B — live trading stabilization & performance control (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase20b.config import DEFAULT_STRIDE, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, OBSERVATION_DAYS
from tradingbot.ml.phase20b.orchestrator import run_phase20b_stabilization


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 20B live stabilization analysis")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--days", type=int, default=OBSERVATION_DAYS)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase20b_stabilization(
        symbol=args.symbol,
        timeframe=args.timeframe,
        base_dir=args.base_dir,
        stride=args.stride,
        days=args.days,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "overall_score": result["health"].get("overall_score"),
        "performance": result["performance"].get("overall"),
        "data_source": result["final_report"].get("data_source"),
    }, indent=2))
    return 0 if result["verdict"] == "LIVE_SYSTEM_STABLE" else 1


if __name__ == "__main__":
    sys.exit(main())
