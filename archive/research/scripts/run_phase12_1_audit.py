#!/usr/bin/env python3
"""Phase 12.1 — strategy architecture audit CLI (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.audit.phase12_1.report_generator import run_phase12_1_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 12.1 strategy architecture audit")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--run", default="phase11_v1", help="Paper run id for replay audit")
    parser.add_argument("--base-dir", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_phase12_1_audit(
        symbol=args.symbol,
        timeframe=args.timeframe,
        paper_run_id=args.run,
        base_dir=args.base_dir,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
