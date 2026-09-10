"""Phase 55 — feature importance & noise audit on v7 (research only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase55" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"


def feature_noise_audit(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    sample_rows: int = 8000,
    seed: int = 42,
) -> dict[str, Any]:
    """Rank features by RF importance; flag low-importance and high-correlation noise."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler

    work = df[df[label_col].isin([0, 1])].copy()
    if len(work) > sample_rows:
        work = work.sample(n=sample_rows, random_state=seed)

    X = work[feature_cols].astype(float).fillna(0)
    y = work[label_col].astype(int).values
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)

    rf = RandomForestClassifier(n_estimators=80, max_depth=6, random_state=seed, min_samples_leaf=10)
    rf.fit(X_s, y)
    importances = {c: round(float(v), 6) for c, v in zip(feature_cols, rf.feature_importances_)}
    ranked = sorted(importances.items(), key=lambda x: -x[1])

    corr = X.corr().abs()
    high_corr_pairs: list[dict] = []
    for i, c1 in enumerate(feature_cols):
        for c2 in feature_cols[i + 1:]:
            val = float(corr.loc[c1, c2])
            if val >= 0.85:
                high_corr_pairs.append({"a": c1, "b": c2, "corr": round(val, 4)})

    median_imp = float(np.median(list(importances.values())))
    noise_features = [c for c, v in importances.items() if v < median_imp * 0.25]
    top_features = [c for c, _ in ranked[:10]]

    return {
        "sample_rows": len(work),
        "feature_count": len(feature_cols),
        "top_features": top_features,
        "importance_ranked": [{"feature": c, "importance": v} for c, v in ranked],
        "noise_features": noise_features,
        "noise_feature_count": len(noise_features),
        "high_correlation_pairs": high_corr_pairs[:20],
        "median_importance": round(median_imp, 6),
    }


def run_phase55() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns

    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    df = pd.read_parquet(V7_PATH)
    feats = feature_columns(df)
    audit = feature_noise_audit(df, "label_v3", feats)

    verdict = "FEATURE_AUDIT_COMPLETE"
    if audit["noise_feature_count"] >= 10:
        verdict = "HIGH_NOISE_FEATURES"

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "rows": len(df),
        **audit,
    }


def write_all(data: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "feature_audit.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase55/artifacts/feature_audit.json", flush=True)
    report = {
        "phase": "55",
        "title": "Feature Importance & Noise Audit",
        "title_fa": "اهمیت ویژگی و ممیزی نویز",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "top_features": data.get("top_features"),
        "noise_feature_count": data.get("noise_feature_count"),
        "noise_features": data.get("noise_features"),
    }
    (ROOT / "phase55_final_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("  wrote phase55_final_report.json", flush=True)


def main() -> None:
    data = run_phase55()
    write_all(data)
    print(json.dumps({
        "verdict": data["verdict"],
        "noise_features": data.get("noise_feature_count"),
        "top": data.get("top_features", [])[:5],
    }, indent=2))


if __name__ == "__main__":
    main()
