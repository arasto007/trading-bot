#!/usr/bin/env python3
"""Phase 9.8 walk-forward validation CLI (offline, CPU-only)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.walk_forward import WalkForwardEngine
from tradingbot.ml.research.walk_forward.report_generator import load_walk_forward_report

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run walk-forward validation (Phase 9.8)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", default="phase9_6_best", help="Reference model alias (read-only)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.report_only:
        report = load_walk_forward_report(args.base_dir)
        print(json.dumps(report, indent=2))
        return 0

    if args.model not in ("phase9_6_best", "phase9.6", "phase9_6"):
        logger.warning("Phase 9.8 uses phase9_6_best artifacts; ignoring model=%s", args.model)

    engine = WalkForwardEngine(base_dir=args.base_dir, seed=args.seed)
    result = engine.run(args.symbol, args.timeframe)
    print(json.dumps(result.to_dict(), indent=2))

    if result.blocked:
        logger.error("Walk-forward blocked: %s", result.block_reason)
        return 1
    logger.info(
        "Phase 9.8 complete: %s windows, robustness=%.2f, decision=%s",
        result.window_count,
        result.robustness_score,
        result.final_decision,
    )
    return 0 if result.final_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
