#!/usr/bin/env python3
"""Phase 14.10 — walk-forward stability recovery CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase14_10.orchestrator import run_phase14_10_stability


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.10 walk-forward stability recovery")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--baseline-robustness", type=float, default=0.17)
    args = parser.parse_args(argv)

    result = run_phase14_10_stability(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        base_dir=args.base_dir,
        quick=args.quick,
        baseline_robustness=args.baseline_robustness,
    )

    summary = result.summary
    root_causes = summary.get("root_cause_ranking", [])
    top5 = root_causes[:5]

    print(result.status)
    print(f"Updated WalkForward Robustness: {summary.get('walk_forward_robustness_updated')}")
    print("Top 5 Root Causes:")
    for i, rc in enumerate(top5, 1):
        impact = rc.get("impact_pct", "?")
        print(f"  #{i} {rc.get('cause')} (impact {impact}%) — {rc.get('evidence')}")
    print(f"READY_FOR_PHASE15: {summary.get('READY_FOR_PHASE15')}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
