#!/usr/bin/env python3
"""Phase 10.1 — ML kernel shadow integration CLI (kernel pipeline, no real orders)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.integration.config import KernelShadowConfig
from tradingbot.ml.integration.kernel_shadow_runner import KernelShadowRunner

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ML kernel shadow (Phase 10.1 — kernel integrated, no orders)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--mode", default="shadow", choices=["shadow", "replay", "live_shadow"])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--risk", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--run", default=None, help="Run id e.g. kernel_run_v1")
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

    runner = KernelShadowRunner(base_dir=args.base_dir)

    if args.report_only:
        if not args.run:
            logger.error("--report-only requires --run")
            return 2
        print(json.dumps(runner.report_only(args.run), indent=2))
        return 0

    mode = "live_shadow" if args.mode == "live_shadow" else "replay"
    config = KernelShadowConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        mode=mode,
        shadow_days=args.days,
        risk_pct=args.risk / 100.0,
        seed=args.seed,
    )

    result = runner.run(config, run_id=args.run)
    print(json.dumps(result.to_dict(), indent=2))
    logger.info(
        "Kernel shadow complete: %s ML signals, %s risk allowed, %s blocked, run_id=%s",
        result.ml_signals,
        result.risk_allowed,
        result.execution_blocked,
        result.run_id,
    )
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
