#!/usr/bin/env python3
"""Phase 38 — Walk-forward retrain on dataset_v3 with threshold sweep (research only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase36" / "artifacts"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_phase38() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase40.retrain_sweep import walk_forward_retrain

    path = ARTIFACTS / "dataset_v3_aligned.parquet"
    if not path.exists():
        return {"verdict": "INSUFFICIENT_DATA", "error": "dataset_v3 missing — run phase36/39 first"}

    df = pd.read_parquet(path)
    feats = feature_columns(df)
    data = walk_forward_retrain(df, "label_v3", feats, model_name="random_forest")
    data["now"] = NOW
    data["phase36_baseline_test_pf"] = 0.7333
    data["mean_pf"] = data.get("mean_best_pf", 0)
    data["pf_vs_phase36_logistic"] = round(float(data.get("mean_pf", 0)) - 0.7333, 4)
    return data


def main() -> None:
    data = run_phase38()
    (ROOT / "phase38_final_report.json").write_text(json.dumps({"phase": "38", **data}, indent=2, default=str), encoding="utf-8")
    (ROOT / "walk_forward_retrain_v3.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase38_final_report.json", flush=True)
    print(json.dumps({"verdict": data["verdict"], "mean_pf": data.get("mean_pf"), "mean_auc": data.get("mean_auc")}, indent=2))


if __name__ == "__main__":
    main()
