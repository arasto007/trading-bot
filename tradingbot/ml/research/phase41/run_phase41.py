#!/usr/bin/env python3
"""Phase 41 — Advanced model search + label generalization audit."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

ARTIFACT = ROOT / "tradingbot" / "ml" / "research" / "phase39" / "artifacts" / "dataset_v3_expanded.parquet"


def run_phase41() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase41.model_search import search_models

    if not ARTIFACT.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "run phase39 first"}

    df = pd.read_parquet(ARTIFACT)
    feats = feature_columns(df)
    search = search_models(df, "label_v3", feats)

    mean_pf = float(search.get("mean_best_pf", 0) or 0)
    mean_auc = float(search.get("mean_auc", 0) or 0)
    if mean_pf >= 1.3 and mean_auc >= 0.55:
        gate = "INTEGRATION_REVIEW_ELIGIBLE"
    elif mean_pf >= 1.0:
        gate = "MARGINAL_CONTINUE_RESEARCH"
    else:
        gate = "BLOCK_PRODUCTION_INTEGRATION"

    return {
        "now": NOW,
        "verdict": search.get("verdict", "RETRAIN_INSUFFICIENT"),
        "integration_gate": gate,
        "best_model": search.get("best_model"),
        "mean_best_pf": mean_pf,
        "mean_auc": mean_auc,
        "dataset_rows": len(df),
        "per_year_labels": search.get("per_year_labels"),
        "models_tested": list((search.get("models") or {}).keys()),
        "model_results": search.get("models"),
        "phase40_best_pf": 0.6779,
        "pf_delta_vs_phase40": round(mean_pf - 0.6779, 4),
    }


def main() -> None:
    data = run_phase41()
    (ROOT / "phase41_final_report.json").write_text(
        json.dumps({"phase": "41", "title": "Advanced Model Search", **data}, indent=2, default=str),
        encoding="utf-8",
    )
    (ROOT / "advanced_model_search_v3.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase41_final_report.json", flush=True)
    print(json.dumps({"verdict": data["verdict"], "gate": data["integration_gate"], "best_model": data.get("best_model")}, indent=2))


if __name__ == "__main__":
    main()
