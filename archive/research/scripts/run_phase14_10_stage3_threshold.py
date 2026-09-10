#!/usr/bin/env python3
"""Phase 14.10 Stage 3 — per-year threshold replay CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase14_10.stage3_threshold_replay import run_stage3_threshold_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.10 Stage 3 threshold replay")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--stage1", default=None, help="Path to yearly_statistics.json")
    args = parser.parse_args(argv)

    result = run_stage3_threshold_replay(base_dir=args.base_dir, stage1_path=args.stage1)
    print(json.dumps({
        "status": "OK",
        "output": result["output_path"],
        "optimal_threshold_per_year": result.get("optimal_threshold_per_year"),
        "mean_threshold_spread_pf": result.get("mean_threshold_spread_pf"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
