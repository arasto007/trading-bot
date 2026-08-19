#!/usr/bin/env python3
"""Offline feature analysis — quality and correlation reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.features.quality.feature_report import save_reports
from tradingbot.ml.features.registry import export_json, validate_integrity, validate_json_file
from tradingbot.ml.features.scaling import fit_scaler_metadata, save_scaler_metadata
from tradingbot.ml.features.store import FeatureStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze ML feature parquet (Phase 2.1)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--correlation-threshold", type=float, default=0.92)
    parser.add_argument("--export-registry", action="store_true", help="Refresh features.json")
    args = parser.parse_args()

    if args.export_registry:
        path = export_json()
        print(f"Exported registry: {path}")

    reg_errors = validate_integrity()
    json_errors = validate_json_file()
    if reg_errors or json_errors:
        print("Registry validation FAILED:")
        for e in reg_errors + json_errors:
            print(f"  - {e}")
        return 1

    store = FeatureStore()
    df = store.load(args.symbol, args.timeframe)
    if df is None or df.empty:
        print(f"No features found for {args.symbol} {args.timeframe}")
        return 1

    feature_cols = [c for c in df.columns if c != "feature_schema_version"]
    df_features = df[feature_cols]

    scaler = fit_scaler_metadata(df_features, args.symbol, args.timeframe)
    scaler_path = save_scaler_metadata(scaler)

    paths = save_reports(
        df_features,
        args.symbol,
        args.timeframe,
        correlation_threshold=args.correlation_threshold,
    )

    summary = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "rows": len(df),
        "feature_schema_version": FeatureStore.read_schema_version(df),
        "scaler_metadata": str(scaler_path),
        "reports": {k: str(v) for k, v in paths.items()},
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
