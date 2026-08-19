#!/usr/bin/env python3
"""Phase 14.10 Stage 5 — final report CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase14_10.stage5_final_report import build_final_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.10 Stage 5 final report")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--yearly-stats", default=None)
    parser.add_argument("--drift", default=None)
    parser.add_argument("--threshold", default=None)
    parser.add_argument("--policy", default=None)
    args = parser.parse_args(argv)

    result = build_final_report(
        base_dir=args.base_dir,
        yearly_path=args.yearly_stats,
        drift_path=args.drift,
        threshold_path=args.threshold,
        policy_path=args.policy,
    )
    print(json.dumps({
        "status": result["PHASE_14_10_STATUS"],
        "READY_FOR_PHASE15": result["READY_FOR_PHASE15"],
        "output": result["output_path"],
    }, indent=2))
    return 0 if result["PHASE_14_10_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
