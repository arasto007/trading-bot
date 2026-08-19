#!/usr/bin/env python3
"""Phase 16B — kernel-level validation and throughput stress test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase16b.config import (
    DEFAULT_SEED,
    DEFAULT_STRIDES,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    DEFAULT_WINDOWS,
)
from tradingbot.ml.research.phase16b.orchestrator import run_phase16b


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 16B kernel validation")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--windows", default="90,180,365")
    p.add_argument("--stride", default="5,10", dest="strides")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    windows = tuple(int(x.strip()) for x in args.windows.split(","))
    strides = tuple(int(x.strip()) for x in args.strides.split(","))

    result = run_phase16b(
        symbol=args.symbol,
        timeframe=args.timeframe,
        windows=windows,
        strides=strides,
        seed=args.seed,
        base_dir=args.base_dir,
    )
    print(json.dumps({"verdict": result["verdict"], "reports_dir": result["reports_dir"]}, indent=2))
    return 0 if result["verdict"] != "NEEDS_REWORK" else 1


if __name__ == "__main__":
    sys.exit(main())
