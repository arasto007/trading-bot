#!/usr/bin/env python3
"""Phase 36 — Aligned Dataset V3 + Chronological Retrain Validation."""

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


def _load_v2() -> pd.DataFrame | None:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.dataset.store import DatasetStore

    base = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    return DatasetStore(base).load_v2("XAUUSD", "M5")


def _load_candles() -> pd.DataFrame | None:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.stores.candle_store import CandleStore

    raw = CandleStore(load_legacy_config().get("BASE_DIR")).load("XAUUSD", "M5")
    if raw is None or raw.empty:
        return None
    if not isinstance(raw.index, pd.DatetimeIndex):
        if "timestamp" in raw.columns:
            raw = raw.set_index("timestamp")
    raw.index = pd.to_datetime(raw.index, utc=True)
    return raw.sort_index()


def run_phase36() -> tuple[dict, pd.DataFrame]:
    from tradingbot.ml.research.phase36.build_dataset_v3 import build_aligned_rows, feature_columns
    from tradingbot.ml.research.phase36.retrain_validation import train_eval_chronological

    v2 = _load_v2()
    candles = _load_candles()
    if v2 is None or candles is None:
        return {"verdict": "INSUFFICIENT_DATA"}, pd.DataFrame()

    v3 = build_aligned_rows(v2, candles)
    if v3.empty:
        return {"verdict": "BUILD_FAILED", "rows": 0}, v3

    feats = feature_columns(v3)
    v2_eval = train_eval_chronological(v3, "label_v2", feats)
    v3_eval = train_eval_chronological(v3, "label_v3", feats)

    changed = int(v3["label_changed"].sum())
    v3_wr = round(float(v3["label_v3"].mean()) * 100, 2)
    v2_wr = round(float(v3["label_v2"].mean()) * 100, 2)

    test_pf_v2 = (v2_eval.get("test") or {}).get("pf", 0)
    test_pf_v3 = (v3_eval.get("test") or {}).get("pf", 0)
    test_auc_v2 = (v2_eval.get("test") or {}).get("auc", 0)
    test_auc_v3 = (v3_eval.get("test") or {}).get("auc", 0)

    if test_pf_v3 >= 1.3 and test_auc_v3 >= 0.55:
        verdict = "RETRAIN_PROMISING"
    elif test_pf_v3 > test_pf_v2 and test_auc_v3 >= test_auc_v2:
        verdict = "V3_IMPROVES_OVER_V2"
    elif test_pf_v3 >= 1.0:
        verdict = "V3_MARGINAL"
    else:
        verdict = "V3_INSUFFICIENT"

    return {
        "now": NOW,
        "verdict": verdict,
        "dataset_v3_rows": len(v3),
        "dataset_v2_overlap_rows": len(v3),
        "labels_changed": changed,
        "labels_changed_pct": round(changed / max(len(v3), 1) * 100, 2),
        "label_win_rate_v2_pct": v2_wr,
        "label_win_rate_v3_pct": v3_wr,
        "feature_count": len(feats),
        "retrain_v2": v2_eval,
        "retrain_v3": v3_eval,
        "comparison": {
            "test_pf_delta": round(test_pf_v3 - test_pf_v2, 4),
            "test_auc_delta": round(test_auc_v3 - test_auc_v2, 4),
            "test_pf_v2": test_pf_v2,
            "test_pf_v3": test_pf_v3,
        },
    }, v3


def write_all(data: dict, v3: pd.DataFrame) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if v3 is not None and not v3.empty:
        v3.to_parquet(ARTIFACTS / "dataset_v3_aligned.parquet", index=False)

    def w(name: str, payload: dict) -> None:
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    w("dataset_v3_build_report.json", {"timestamp_utc": data["now"], **{k: data[k] for k in data if k != "now"}})
    w("retrain_validation_v2.json", {"timestamp_utc": data["now"], "evaluation": data.get("retrain_v2")})
    w("retrain_validation_v3.json", {"timestamp_utc": data["now"], "evaluation": data.get("retrain_v3")})
    w("phase36_final_report.json", {
        "phase": "36",
        "title": "Aligned Dataset V3 + Retrain Validation",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "dataset_v3_rows": data.get("dataset_v3_rows"),
        "comparison": data.get("comparison"),
        "retrain_v2_test": data.get("retrain_v2", {}).get("test"),
        "retrain_v3_test": data.get("retrain_v3", {}).get("test"),
        "deliverables": [
            "dataset_v3_build_report.json", "retrain_validation_v2.json",
            "retrain_validation_v3.json", "phase36_final_report.json",
            "tradingbot/ml/research/phase36/artifacts/dataset_v3_aligned.parquet",
        ],
    })


def main() -> None:
    data, v3_df = run_phase36()
    write_all(data, v3_df)
    print(json.dumps({"verdict": data["verdict"], "rows": data.get("dataset_v3_rows"), "comparison": data.get("comparison")}, indent=2))


if __name__ == "__main__":
    main()
