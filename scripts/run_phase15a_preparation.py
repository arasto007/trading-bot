#!/usr/bin/env python3
"""Phase 15A — production integration preparation CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase15a.orchestrator import run_phase15a_preparation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 15A production integration preparation")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--no-freeze", action="store_true", help="Skip trend bundle freeze if missing")
    parser.add_argument("--sample-bars", type=int, default=5)
    args = parser.parse_args(argv)

    result = run_phase15a_preparation(
        symbol=args.symbol,
        timeframe=args.timeframe,
        seed=args.seed,
        base_dir=args.base_dir,
        freeze_if_missing=not args.no_freeze,
        sample_bars=args.sample_bars,
    )
    print(result.status)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
