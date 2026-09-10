#!/usr/bin/env python3
"""Phase 11.5 — research-only optimization & bias audit (no live orders)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase11_5.optimizer_orchestrator import run_phase11_5_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 11.5 research analysis (read-only)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--run", default="phase11_v1", help="Paper run id e.g. phase11_v1")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--iterations", type=int, default=1000, help="Bootstrap/Monte Carlo iterations")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_phase11_5_analysis(
        symbol=args.symbol,
        timeframe=args.timeframe,
        paper_run_id=args.run,
        base_dir=args.base_dir,
        bootstrap_iterations=args.iterations,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.decision == "READY_FOR_PHASE12" else 1


if __name__ == "__main__":
    raise SystemExit(main())
