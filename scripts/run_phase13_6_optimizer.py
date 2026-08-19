#!/usr/bin/env python3
"""Phase 13.6 — router optimizer research CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.router_optimizer.orchestrator import run_phase13_6_optimizer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 13.6 router optimizer research")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_phase13_6_optimizer(
        symbol=args.symbol,
        timeframe=args.timeframe,
        seed=args.seed,
        base_dir=args.base_dir,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
