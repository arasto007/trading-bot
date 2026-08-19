#!/usr/bin/env python3
"""Train offline baseline ML models — Phase 4.0 (research only, not live)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.models.training import MODEL_CHOICES, train_baseline_model


def main() -> int:
    parser = argparse.ArgumentParser(description="Train baseline ML model (offline research only)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", required=True, choices=MODEL_CHOICES)
    parser.add_argument("--version", default="1.0")
    args = parser.parse_args()

    print(f"Training {args.model} on {args.symbol} {args.timeframe} (offline — not connected to live trading)")
    result = train_baseline_model(
        args.symbol,
        args.timeframe,
        args.model,
        version=args.version,
    )
    print(json.dumps(
        {
            "artifact_dir": result["artifact_dir"],
            "registry": result["registry"],
            "test_metrics": (result.get("test") or {}).get("metrics"),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
