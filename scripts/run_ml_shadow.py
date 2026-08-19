#!/usr/bin/env python3
"""Phase 10 ML shadow integration CLI (observation only — no real orders)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.shadow.config import ShadowConfig
from tradingbot.ml.shadow.shadow_engine import MLShadowEngine

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ML shadow integration (Phase 10 — no orders)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", default="phase9_9_best")
    parser.add_argument("--mode", default="replay", choices=["replay", "live_shadow"])
    parser.add_argument("--risk", type=float, default=0.5, help="Risk percent per trade")
    parser.add_argument("--days", type=int, default=30, help="Shadow window in days (replay)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--run", default=None, help="Run id (default auto)")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    engine = MLShadowEngine(base_dir=args.base_dir, seed=args.seed)

    if args.report_only:
        if not args.run:
            logger.error("--report-only requires --run")
            return 2
        report = engine.report_only(args.run)
        print(json.dumps(report, indent=2))
        return 0

    config = ShadowConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        model_alias=args.model,
        mode=args.mode,
        risk_pct=args.risk / 100.0,
        shadow_days=args.days,
        use_mt5=args.mode == "live_shadow",
        seed=args.seed,
    )

    result = engine.run(config, run_id=args.run)
    print(json.dumps(result.to_dict(), indent=2))
    logger.info(
        "Shadow run complete: %s signals, %s virtual trades, run_id=%s",
        result.num_signals,
        result.num_virtual_trades,
        result.run_id,
    )
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
