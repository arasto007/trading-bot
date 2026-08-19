#!/usr/bin/env python3
"""Phase 39 — Expand candle coverage and rebuild dataset_v3 on fullest history."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase39" / "artifacts"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_v2() -> pd.DataFrame | None:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.dataset.store import DatasetStore

    base = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    return DatasetStore(base).load_v2("XAUUSD", "M5")


def run_phase39() -> tuple[dict, pd.DataFrame]:
    from tradingbot.ml.research.phase36.retrain_validation import train_eval_chronological
    from tradingbot.ml.research.phase39.candle_sources import audit_report, resolve_fullest_candles
    from tradingbot.ml.research.phase39.expand_dataset import build_aligned_rows_expanded, feature_columns

    audit = audit_report()
    candles = resolve_fullest_candles()
    v2 = _load_v2()
    if v2 is None or candles is None or candles.empty:
        return {"verdict": "INSUFFICIENT_DATA", "audit": audit}, pd.DataFrame()

    v3 = build_aligned_rows_expanded(v2, candles)
    if v3.empty:
        return {"verdict": "BUILD_FAILED", "audit": audit, "rows": 0}, v3

    feats = feature_columns(v3)
    v3_eval = train_eval_chronological(v3, "label_v3", feats)

    overlap = len(v3)
    total_v2 = len(v2)
    coverage_pct = round(overlap / max(total_v2, 1) * 100, 2)
    changed = int(v3["label_changed"].sum())
    test_pf = (v3_eval.get("test") or {}).get("pf", 0)
    test_auc = (v3_eval.get("test") or {}).get("auc", 0)

    prev_rows = 1578
    row_gain_pct = round((overlap - prev_rows) / max(prev_rows, 1) * 100, 2)

    if coverage_pct >= 85 and test_pf >= 1.0 and test_auc >= 0.55:
        verdict = "EXPANSION_READY_FOR_RETRAIN"
    elif overlap > prev_rows and test_auc >= 0.55:
        verdict = "EXPANSION_IMPROVES_COVERAGE"
    elif overlap > prev_rows:
        verdict = "EXPANSION_MORE_ROWS_ML_STILL_WEAK"
    else:
        verdict = "EXPANSION_INSUFFICIENT"

    return {
        "now": NOW,
        "verdict": verdict,
        "audit": audit,
        "dataset_v2_rows": total_v2,
        "dataset_v3_expanded_rows": overlap,
        "phase36_baseline_rows": prev_rows,
        "row_gain_pct_vs_phase36": row_gain_pct,
        "candle_coverage_pct": coverage_pct,
        "labels_changed": changed,
        "labels_changed_pct": round(changed / max(overlap, 1) * 100, 2),
        "label_win_rate_v3_pct": round(float(v3["label_v3"].mean()) * 100, 2),
        "feature_count": len(feats),
        "retrain_v3_expanded": v3_eval,
        "comparison_vs_phase36": {
            "rows_delta": overlap - prev_rows,
            "test_pf": test_pf,
            "test_auc": test_auc,
        },
    }, v3


def write_all(data: dict, v3: pd.DataFrame) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if v3 is not None and not v3.empty:
        v3.to_parquet(ARTIFACTS / "dataset_v3_expanded.parquet", index=False)
        phase36_art = ROOT / "tradingbot" / "ml" / "research" / "phase36" / "artifacts"
        phase36_art.mkdir(parents=True, exist_ok=True)
        v3.to_parquet(phase36_art / "dataset_v3_aligned.parquet", index=False)

    payloads = {
        "candle_source_audit.json": data.get("audit", {}),
        "dataset_v3_expansion_report.json": {
            "timestamp_utc": data["now"],
            **{k: v for k, v in data.items() if k not in ("now", "audit")},
        },
        "phase39_final_report.json": {
            "phase": "39",
            "title": "Candle Coverage Expansion + Dataset V3 Rebuild",
            "timestamp_utc": data["now"],
            "verdict": data["verdict"],
            "dataset_v3_expanded_rows": data.get("dataset_v3_expanded_rows"),
            "candle_coverage_pct": data.get("candle_coverage_pct"),
            "comparison_vs_phase36": data.get("comparison_vs_phase36"),
            "deliverables": [
                "candle_source_audit.json",
                "dataset_v3_expansion_report.json",
                "phase39_final_report.json",
                "tradingbot/ml/research/phase39/artifacts/dataset_v3_expanded.parquet",
            ],
        },
    }
    for name, payload in payloads.items():
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)


def main() -> None:
    data, v3_df = run_phase39()
    write_all(data, v3_df)
    print(
        json.dumps(
            {
                "verdict": data["verdict"],
                "rows": data.get("dataset_v3_expanded_rows"),
                "coverage_pct": data.get("candle_coverage_pct"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
