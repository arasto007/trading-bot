#!/usr/bin/env python3
"""Phase 14.10 Stage 1 — fast yearly statistics CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase14_10.stage1_yearly_statistics import run_stage1_yearly_statistics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.10 Stage 1 yearly statistics")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args(argv)

    result = run_stage1_yearly_statistics(
        symbol=args.symbol,
        timeframe=args.timeframe,
        seed=args.seed,
        base_dir=args.base_dir,
    )
    print(json.dumps(
        {
            "status": "OK",
            "active_years": result.get("active_years"),
            "output": str(result.get("output_path", "data/ml/reports/phase14_10/yearly_statistics.json")),
            "per_year_summary": {
                y: {"pf": v.get("profit_factor"), "trades": v.get("trades"), "skipped": v.get("skipped")}
                for y, v in result.get("per_year", {}).items()
            },
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
