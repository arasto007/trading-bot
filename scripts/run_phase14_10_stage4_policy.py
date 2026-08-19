#!/usr/bin/env python3
"""Phase 14.10 Stage 4 — adaptive threshold policy CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase14_10.stage4_adaptive_threshold_policy import build_adaptive_threshold_policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.10 Stage 4 adaptive threshold policy")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--yearly-stats", default=None)
    parser.add_argument("--threshold", default=None)
    args = parser.parse_args(argv)

    result = build_adaptive_threshold_policy(
        base_dir=args.base_dir,
        yearly_stats_path=args.yearly_stats,
        threshold_path=args.threshold,
    )
    print(json.dumps({
        "status": "OK",
        "output": result["output_path"],
        "recommendation": result["recommendation"],
        "adopt_adaptive_threshold": result["adopt_adaptive_threshold"],
        "proposed_rule": result["proposed_rule"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
