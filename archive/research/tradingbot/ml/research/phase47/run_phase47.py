#!/usr/bin/env python3
"""Phase 47 — Compare walk-forward retrain: v4 vs v5 vs v6."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

DATASETS = {
    "v4_full": ROOT / "tradingbot" / "ml" / "research" / "phase42" / "artifacts" / "dataset_v4_spread_patched.parquet",
    "v5_structure": ROOT / "tradingbot" / "ml" / "research" / "phase45" / "artifacts" / "dataset_v5_structure.parquet",
    "v6_ml_signals": ROOT / "tradingbot" / "ml" / "research" / "phase46" / "artifacts" / "dataset_v6_ml_signals.parquet",
}


def run_phase47() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase40.retrain_sweep import walk_forward_retrain

    results: dict[str, dict] = {}
    best_name = ""
    best_pf = -1.0

    for name, path in DATASETS.items():
        if not path.is_file():
            results[name] = {"verdict": "MISSING", "path": str(path)}
            continue
        df = pd.read_parquet(path)
        if len(df) < 80:
            results[name] = {"verdict": "INSUFFICIENT_ROWS", "rows": len(df)}
            continue
        feats = feature_columns(df)
        res = walk_forward_retrain(
            df, "label_v3", feats,
            model_name="random_forest",
            thresholds=[0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
        )
        results[name] = res
        pf = float(res.get("mean_best_pf", 0) or 0)
        if pf > best_pf:
            best_pf = pf
            best_name = name

    overall = results.get(best_name, {})
    mean_auc = float(overall.get("mean_auc", 0) or 0)

    if best_pf >= 1.3 and mean_auc >= 0.55:
        verdict = "RETRAIN_READY_FOR_INTEGRATION_REVIEW"
    elif best_pf >= 1.0:
        verdict = "RETRAIN_MARGINAL"
    elif best_pf > 0.79:
        verdict = "RETRAIN_IMPROVING"
    else:
        verdict = "RETRAIN_INSUFFICIENT"

    return {
        "now": NOW,
        "verdict": verdict,
        "best_dataset": best_name,
        "mean_best_pf": round(best_pf, 4),
        "mean_auc": round(mean_auc, 4),
        "dataset_results": results,
        "phase43_baseline_pf": 0.791,
        "pf_delta_vs_phase43": round(best_pf - 0.791, 4),
    }


def main() -> None:
    data = run_phase47()
    (ROOT / "phase47_final_report.json").write_text(
        json.dumps({"phase": "47", "title": "Dataset Comparison Retrain", **data}, indent=2, default=str),
        encoding="utf-8",
    )
    (ROOT / "dataset_comparison_retrain.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase47_final_report.json", flush=True)
    print(json.dumps({
        "verdict": data["verdict"],
        "best_dataset": data.get("best_dataset"),
        "mean_best_pf": data.get("mean_best_pf"),
    }, indent=2))


if __name__ == "__main__":
    main()
