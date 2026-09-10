#!/usr/bin/env python3
"""Phase 19D — final production certification (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase19d.config import DEFAULT_SYMBOL, DEFAULT_STRIDE, DEFAULT_TIMEFRAME
from tradingbot.ml.phase19d.orchestrator import run_phase19d_certification


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 19D final production certification")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase19d_certification(
        symbol=args.symbol,
        timeframe=args.timeframe,
        base_dir=args.base_dir,
        stride=args.stride,
        project_root=ROOT,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "overall_score": result["final_score"].get("overall_score"),
        "all_gates_pass": result["deployment"].get("all_gates_pass"),
        "performance_3y": result["final_report"].get("performance_3y"),
    }, indent=2))
    return 0 if result["verdict"] != "NOT_APPROVED_FOR_LIVE" else 1


if __name__ == "__main__":
    sys.exit(main())
