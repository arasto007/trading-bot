#!/usr/bin/env python3
"""Phase 14.10 Stage 2 — yearly drift analysis CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase14_10.stage2_drift_analysis import analyze_yearly_drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.10 Stage 2 yearly drift analysis")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--input", default=None, help="Path to yearly_statistics.json")
    args = parser.parse_args(argv)

    result = analyze_yearly_drift(base_dir=args.base_dir, input_path=args.input)
    print(json.dumps({
        "status": "OK",
        "output": result["output_path"],
        "best_year": result["best_year"],
        "worst_year": result["worst_year"],
        "largest_drift": result["largest_drift"],
        "largest_pf_drop": result["largest_pf_drop"],
        "largest_trade_drop": result["largest_trade_drop"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
