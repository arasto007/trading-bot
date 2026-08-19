#!/usr/bin/env python3
"""Phase 15B — kernel integration validation CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.integration.phase15b_orchestrator import run_phase15b_validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 15B kernel integration validation")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args(argv)

    result = run_phase15b_validation(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        base_dir=args.base_dir,
        stride=args.stride,
    )
    print(result.status)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
