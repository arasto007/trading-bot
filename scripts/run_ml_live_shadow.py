#!/usr/bin/env python3
"""Phase 10.2 — ML live shadow validation CLI (MT5 read-only, no orders)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.integration.live_preflight import run_live_preflight, scan_live_shadow_ast
from tradingbot.ml.integration.live_shadow_runner import LiveShadowConfig, LiveShadowRunner

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ML live shadow validation (Phase 10.2 — MT5 read-only)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", default="phase9_9_best")
    parser.add_argument("--run", default=None, help="Run id e.g. live_run_v1")
    parser.add_argument("--risk", type=float, default=0.5)
    parser.add_argument("--hours", type=int, default=None, help="Poll duration in hours")
    parser.add_argument("--days", type=int, default=7, help="Historical shadow window in days")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
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
        logger.error("AST safety violations: %s", violations)
        return 2

    runner = LiveShadowRunner(base_dir=args.base_dir)

    if args.report_only:
        if not args.run:
            logger.error("--report-only requires --run")
            return 2
        print(json.dumps(runner.report_only(args.run), indent=2))
        return 0

    if args.preflight_only:
        report = run_live_preflight(args.symbol, args.timeframe, base_dir=args.base_dir)
        print(json.dumps(report, indent=2))
        return 0 if report.get("preflight_pass") else 1

    mode = "poll" if args.hours else "historical"
    config = LiveShadowConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        model=args.model,
        risk_pct=args.risk / 100.0,
        shadow_days=args.days,
        shadow_hours=args.hours,
        mode=mode,
        seed=args.seed,
        skip_preflight=args.skip_preflight,
    )

    result = runner.run(config, run_id=args.run)
    print(json.dumps(result.to_dict(), indent=2))
    logger.info(
        "Live shadow complete: cycles=%s ml_in_kernel=%s risk_allowed=%s virtual_trades=%s",
        result.metrics.get("kernel_cycles"),
        result.metrics.get("ml_in_kernel"),
        result.metrics.get("risk_allowed"),
        result.metrics.get("virtual_trades"),
    )
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
