#!/usr/bin/env python3
"""Phase 9.10 paper trading & shadow validation CLI (no real orders)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.paper_trading.shadow_engine import ShadowEngine

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper trading shadow validation (Phase 9.10)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", default="phase9_9_best", help="Frozen Phase 9.9 model alias")
    parser.add_argument("--risk", type=float, default=0.5, help="Risk percent per trade")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--run", default=None, help="Run id (default auto)")
    parser.add_argument("--shadow-days", type=int, default=30, help="Shadow validation window in days")
    parser.add_argument("--mode", default="dataset_shadow", choices=["dataset_shadow", "candle_shadow"])
    parser.add_argument("--use-mt5", action="store_true", help="Read-only MT5 candles (no orders)")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    engine = ShadowEngine(base_dir=args.base_dir, seed=args.seed)

    if args.report_only:
        if not args.run:
            logger.error("--report-only requires --run")
            return 2
        report = engine.report_only(args.run)
        print(json.dumps(report, indent=2))
        return 0

    if args.model not in ("phase9_9_best", "phase9.9", "phase9_9"):
        logger.warning("Only phase9_9_best supported; got %s", args.model)

    result = engine.run(
        args.symbol,
        args.timeframe,
        run_id=args.run,
        risk_pct=args.risk / 100.0,
        shadow_days=args.shadow_days,
        mode=args.mode,
        use_mt5=args.use_mt5,
    )
    print(json.dumps(result.to_dict(), indent=2))

    if result.blocked:
        logger.error("Paper trading blocked: %s", result.block_reason)
        return 1
    logger.info("Paper run complete: %s trades, run_id=%s", result.num_trades, result.run_id)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
