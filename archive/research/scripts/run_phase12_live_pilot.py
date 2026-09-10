#!/usr/bin/env python3
"""Phase 12 — controlled live pilot CLI."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.live_pilot.config import PilotConfig, resolve_mode
from tradingbot.ml.live_pilot.live_controller import LiveController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 12 controlled live pilot")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--mode", default=None, choices=["SHADOW", "PAPER", "PILOT"])
    parser.add_argument("--run", default="v1", help="Run id e.g. v1 → run_v1")
    parser.add_argument("--risk", type=float, default=0.25, help="Risk percent e.g. 0.25")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-model-validation", action="store_true")
    parser.add_argument("--regime-filter-block", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    mode = resolve_mode(args.mode)
    config = PilotConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        mode=mode,
        run_id=args.run,
        risk_pct=args.risk / 100.0,
        pilot_days=args.days,
        skip_preflight=args.skip_preflight,
        skip_model_validation=args.skip_model_validation,
        regime_filter_block=args.regime_filter_block,
    )

    controller = LiveController(base_dir=args.base_dir)
    result = controller.run(config)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
