#!/usr/bin/env python3
"""Phase 43 — Retrain on balanced event subsets with walk-forward threshold sweep."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

V4_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase42" / "artifacts" / "dataset_v4_spread_patched.parquet"
V3_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase39" / "artifacts" / "dataset_v3_expanded.parquet"


def _load_base() -> pd.DataFrame | None:
    if V4_PATH.is_file():
        return pd.read_parquet(V4_PATH)
    if V3_PATH.is_file():
        return pd.read_parquet(V3_PATH)
    return None


def run_phase43() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase40.retrain_sweep import walk_forward_retrain
    from tradingbot.ml.research.phase43.subset_builder import build_subsets, subset_summary

    base = _load_base()
    if base is None or base.empty:
        return {"verdict": "INSUFFICIENT_DATA", "error": "run phase42 first"}

    feats = feature_columns(base)
    subsets = build_subsets(base)
    results: dict[str, dict] = {}
    best_name = ""
    best_pf = -1.0

    for name, df in subsets.items():
        if len(df) < 200:
            results[name] = {"verdict": "INSUFFICIENT_ROWS", "rows": len(df)}
            continue
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
    elif best_pf > 0.77:
        verdict = "RETRAIN_IMPROVING"
    else:
        verdict = "RETRAIN_INSUFFICIENT"

    return {
        "now": NOW,
        "verdict": verdict,
        "best_subset": best_name,
        "mean_best_pf": round(best_pf, 4),
        "mean_auc": round(mean_auc, 4),
        "subset_summary": subset_summary(subsets),
        "subset_results": results,
        "phase41_baseline_pf": 0.766,
        "pf_delta_vs_phase41": round(best_pf - 0.766, 4),
    }


def main() -> None:
    data = run_phase43()
    (ROOT / "phase43_final_report.json").write_text(
        json.dumps({"phase": "43", "title": "Balanced Event Subset Retrain", **data}, indent=2, default=str),
        encoding="utf-8",
    )
    (ROOT / "balanced_subset_retrain.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase43_final_report.json", flush=True)
    print(json.dumps({
        "verdict": data["verdict"],
        "best_subset": data.get("best_subset"),
        "mean_best_pf": data.get("mean_best_pf"),
    }, indent=2))


if __name__ == "__main__":
    main()
