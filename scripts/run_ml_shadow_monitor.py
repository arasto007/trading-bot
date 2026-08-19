#!/usr/bin/env python3
"""Phase 10.4 — long-duration ML shadow monitoring CLI (read-only, no orders)."""

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
from tradingbot.ml.monitoring.long_run_manager import LongRunConfig, LongRunManager

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ML shadow stability monitor (Phase 10.4)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", default="phase9_9_best")
    parser.add_argument("--run", default="stability_run_v1", help="Monitor run id")
    parser.add_argument("--risk", type=float, default=0.5, help="Risk percent e.g. 0.5")
    parser.add_argument("--hours", type=int, default=None, help="Poll duration hours")
    parser.add_argument("--days", type=int, default=7, help="Historical shadow days")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
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

    manager = LongRunManager(base_dir=args.base_dir)

    if args.report_only:
        from tradingbot.ml.data.paths import ml_shadow_monitor_final_report_path

        path = ml_shadow_monitor_final_report_path(args.run, args.base_dir)
        if not path.is_file():
            logger.error("Monitor report not found: %s", path)
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0

    if args.preflight_only:
        report = run_live_preflight(args.symbol, args.timeframe, base_dir=args.base_dir)
        print(json.dumps(report, indent=2))
        return 0 if report.get("preflight_pass") else 1

    config = LongRunConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        model=args.model,
        risk_pct=args.risk / 100.0,
        shadow_days=args.days,
        shadow_hours=args.hours,
        run_id=args.run,
        seed=args.seed,
        skip_preflight=args.skip_preflight,
        resume=args.resume,
    )

    result = manager.run(config)
    print(json.dumps(result.to_dict(), indent=2))
    logger.info(
        "Monitor complete: decision=%s cycles=%s",
        result.decision,
        result.final_report.get("runtime", {}).get("kernel_cycles"),
    )
    return 0 if result.decision == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
