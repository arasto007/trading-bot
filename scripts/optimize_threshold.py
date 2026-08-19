#!/usr/bin/env python3
"""Optimize trading probability threshold — Phase 4.1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.models.training import MODEL_CHOICES
from tradingbot.ml.validation.threshold_optimizer import optimize_threshold


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize model probability threshold")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", required=True, choices=MODEL_CHOICES)
    parser.add_argument("--split", default="validation", choices=("train", "validation", "test"))
    args = parser.parse_args()

    result = optimize_threshold(
        args.symbol,
        args.timeframe,
        args.model,
        split=args.split,
    )
    print(json.dumps(
        {
            "model": result.model,
            "best_threshold": result.best_threshold,
            "expected_R": result.expected_R,
            "winrate": result.winrate,
            "signals": result.signals,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
