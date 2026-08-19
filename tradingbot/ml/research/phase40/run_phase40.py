#!/usr/bin/env python3
"""Phase 40 — Threshold sweep walk-forward retrain on expanded dataset_v3."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

ARTIFACT_CANDIDATES = [
    ROOT / "tradingbot" / "ml" / "research" / "phase39" / "artifacts" / "dataset_v3_expanded.parquet",
    ROOT / "tradingbot" / "ml" / "research" / "phase36" / "artifacts" / "dataset_v3_aligned.parquet",
]


def _load_v3() -> pd.DataFrame | None:
    for path in ARTIFACT_CANDIDATES:
        if path.is_file():
            return pd.read_parquet(path)
    return None


def run_phase40() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase40.retrain_sweep import walk_forward_retrain

    df = _load_v3()
    if df is None or df.empty:
        return {"verdict": "INSUFFICIENT_DATA", "error": "dataset_v3 missing — run phase39 first"}

    feats = feature_columns(df)
    models = ["random_forest", "logistic"]
    results: dict[str, dict] = {}
    best_name = ""
    best_pf = -1.0
    for name in models:
        try:
            res = walk_forward_retrain(df, "label_v3", feats, model_name=name)
        except Exception as exc:
            res = {"verdict": "MODEL_FAILED", "error": str(exc)}
        results[name] = res
        pf = float(res.get("mean_best_pf", 0) or 0)
        if pf > best_pf:
            best_pf = pf
            best_name = name

    overall = results.get(best_name, {})
    return {
        "now": NOW,
        "verdict": overall.get("verdict", "RETRAIN_INSUFFICIENT"),
        "best_model": best_name,
        "models": results,
        "dataset_rows": len(df),
        "phase36_baseline_test_pf": 0.7333,
        "pf_vs_phase36_logistic": round(best_pf - 0.7333, 4),
    }


def main() -> None:
    data = run_phase40()
    (ROOT / "phase40_final_report.json").write_text(
        json.dumps({"phase": "40", "title": "Threshold Sweep Walk-Forward Retrain", **data}, indent=2, default=str),
        encoding="utf-8",
    )
    (ROOT / "threshold_sweep_retrain_v3.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase40_final_report.json", flush=True)
    print(
        json.dumps(
            {"verdict": data["verdict"], "best_model": data.get("best_model"), "models": list(data.get("models", {}))},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
