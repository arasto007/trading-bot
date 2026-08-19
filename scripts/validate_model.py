#!/usr/bin/env python3
"""Full offline model validation — Phase 4.1 (research only, not live)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.models.training import MODEL_CHOICES
from tradingbot.ml.validation.report import run_full_validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full offline model validation")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", required=True, choices=MODEL_CHOICES)
    parser.add_argument("--skip-ablation", action="store_true", help="Skip slow feature ablation")
    args = parser.parse_args()

    print(
        f"Validating {args.model} on {args.symbol} {args.timeframe} "
        "(offline — not connected to live trading)"
    )
    summary = run_full_validation(
        args.symbol,
        args.timeframe,
        args.model,
        skip_ablation=args.skip_ablation,
    )
    print(json.dumps(
        {
            "model": summary.model,
            "optimal_threshold": summary.optimal_threshold.get("best_threshold"),
            "walk_forward_stability": summary.walk_forward.get("stability_score"),
            "trading_simulation": {
                "total_trades": summary.trading_simulation.get("total_trades"),
                "expectancy": summary.trading_simulation.get("expectancy"),
                "max_drawdown": summary.trading_simulation.get("max_drawdown"),
            },
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
