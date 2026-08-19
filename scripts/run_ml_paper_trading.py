#!/usr/bin/env python3
"""Phase 11 — kernel-integrated ML paper trading CLI (virtual execution only)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast
from tradingbot.ml.paper.config import PaperTradingConfig
from tradingbot.ml.paper.paper_engine import KernelPaperEngine

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 11 kernel paper trading (no live orders)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", default="phase9_9_best")
    parser.add_argument("--run", default="phase11_v1", help="Run id e.g. run_phase11_v1")
    parser.add_argument("--risk", type=float, default=0.5)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--hours", type=int, default=None, help="Live paper poll hours")
    parser.add_argument("--mode", default="replay", choices=["replay", "live"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-model-validation", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    os.environ["ENABLE_ML_SHADOW"] = "true"
    os.environ["ML_SHADOW_MODE"] = "true"

    violations = scan_live_shadow_ast()
    if violations:
        logger.error("AST violations: %s", violations)
        return 2

    engine = KernelPaperEngine(base_dir=args.base_dir)

    if args.report_only:
        if not args.run:
            logger.error("--report-only requires --run")
            return 2
        print(json.dumps(engine.report_only(args.run), indent=2))
        return 0

    config = PaperTradingConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        model=args.model,
        risk_pct=args.risk / 100.0,
        paper_days=args.days,
        paper_hours=args.hours,
        mode=args.mode,
        seed=args.seed,
        skip_preflight=args.skip_preflight,
        skip_model_validation=args.skip_model_validation,
    )

    result = engine.run(config, run_id=args.run)
    print(json.dumps(result.to_dict(), indent=2))
    logger.info(
        "Paper run complete: decision=%s trades=%s cycles",
        result.decision,
        result.num_trades,
    )
    return 0 if result.decision == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
