#!/usr/bin/env python3
"""Offline dataset quality analysis — Phase 3."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.dataset.report import save_dataset_quality_report
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.validation import validate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze ML dataset quality (Phase 3)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    store = DatasetStore()
    df = store.load(args.symbol, args.timeframe)
    if df is None or df.empty:
        print(f"No dataset found for {args.symbol} {args.timeframe}")
        return 1

    validation = validate_dataset(df)
    path = save_dataset_quality_report(df, args.symbol, args.timeframe)

    summary = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "rows": len(df),
        "validation_status": validation.status,
        "label_distribution": validation.label_distribution,
        "report_path": str(path),
    }
    print(json.dumps(summary, indent=2))
    return 0 if validation.status != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
