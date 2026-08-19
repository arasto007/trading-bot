#!/usr/bin/env python3
"""Evaluate trained baseline ML model — Phase 4.0."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.models.artifacts import feature_importance_report_path
from tradingbot.ml.models.dataset_loader import load_dataset_splits
from tradingbot.ml.models.evaluator import ModelEvaluator
from tradingbot.ml.models.training import MODEL_CHOICES, load_model


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate trained baseline model")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--model", required=True, choices=MODEL_CHOICES)
    parser.add_argument("--split", default="test", choices=("train", "validation", "test"))
    args = parser.parse_args()

    splits = load_dataset_splits(args.symbol, args.timeframe)
    split_map = {
        "train": (splits.X_train, splits.y_train),
        "validation": (splits.X_val, splits.y_val),
        "test": (splits.X_test, splits.y_test),
    }
    X, y = split_map[args.split]
    if X.empty:
        print(f"Split '{args.split}' is empty")
        return 1

    model = load_model(args.model)
    evaluator = ModelEvaluator()
    result = evaluator.evaluate(
        model, X, y, symbol=args.symbol, timeframe=args.timeframe, split=args.split
    )
    path = evaluator.save_report(result)

    importance = model.feature_importances()
    imp_path = None
    if importance:
        imp_path = feature_importance_report_path(args.model)
        imp_path.parent.mkdir(parents=True, exist_ok=True)
        imp_path.write_text(json.dumps(importance, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(
        {
            "evaluation_report": str(path),
            "feature_importance": str(imp_path) if imp_path else None,
            "result": result.to_dict(),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
