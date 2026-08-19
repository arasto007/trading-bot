#!/usr/bin/env python3
"""SHAP analysis for trained baseline models — offline research only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.models.artifacts import shap_summary_report_path
from tradingbot.ml.models.dataset_loader import load_dataset_splits
from tradingbot.ml.models.training import MODEL_CHOICES, load_model


def main() -> int:
    parser = argparse.ArgumentParser(description="SHAP summary for baseline model (offline)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", required=True, choices=("xgboost", "lightgbm"))
    parser.add_argument("--max-samples", type=int, default=200)
    args = parser.parse_args()

    try:
        import shap
        import numpy as np
    except ImportError:
        print("shap package not installed — pip install shap")
        return 1

    splits = load_dataset_splits(args.symbol, args.timeframe)
    X = splits.X_test if not splits.X_test.empty else splits.X_val
    if X.empty:
        X = splits.X_train
    if X.empty:
        print("No samples available for SHAP analysis")
        return 1

    X_sample = X.head(args.max_samples)
    model = load_model(args.model)

    inner = getattr(model, "_model", None) or getattr(model, "_pipeline", None)
    if inner is None:
        print("Model has no underlying estimator for SHAP")
        return 1

    explainer = shap.TreeExplainer(inner)
    shap_values = explainer.shap_values(X_sample)
    if isinstance(shap_values, list):
        shap_values = shap_values[1]

    mean_abs = np.abs(shap_values).mean(axis=0)
    summary = [
        {"name": col, "mean_abs_shap": round(float(v), 6)}
        for col, v in sorted(zip(X_sample.columns, mean_abs), key=lambda x: -x[1])
    ]

    path = shap_summary_report_path(args.symbol, args.timeframe, args.model)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": args.model,
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "samples": len(X_sample),
        "features": summary[:30],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"shap_report": str(path), "top_features": summary[:10]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
