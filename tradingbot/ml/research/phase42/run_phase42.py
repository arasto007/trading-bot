#!/usr/bin/env python3
"""Phase 42 — Feature parity audit, spread patch, event bias report."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase42" / "artifacts"
V3_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase39" / "artifacts" / "dataset_v3_expanded.parquet"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_phase42() -> tuple[dict, pd.DataFrame]:
    from tradingbot.ml.research.phase36.retrain_validation import train_eval_chronological
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
    from tradingbot.ml.research.phase42.event_bias_audit import event_bias_report
    from tradingbot.ml.research.phase42.feature_parity import (
        audit_feature_parity,
        build_dataset_v4,
    )

    if not V3_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "run phase39 first"}, pd.DataFrame()

    v3 = pd.read_parquet(V3_PATH)
    candles = resolve_fullest_candles()
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES"}, pd.DataFrame()

    parity = audit_feature_parity(v3, sample_size=100)
    bias = event_bias_report(v3, label_col="label_v3")
    v4 = build_dataset_v4(v3, candles)

    feats = feature_columns(v4)
    v3_eval = train_eval_chronological(v3, "label_v3", feats)
    v4_eval = train_eval_chronological(v4, "label_v3", feats)

    test_pf_v3 = (v3_eval.get("test") or {}).get("pf", 0)
    test_pf_v4 = (v4_eval.get("test") or {}).get("pf", 0)
    test_auc_v4 = (v4_eval.get("test") or {}).get("auc", 0)

    if parity["verdict"] == "FEATURE_PARITY_BROKEN":
        verdict = "FEATURE_REBUILD_REQUIRED"
    elif test_pf_v4 > test_pf_v3 and test_auc_v4 >= 0.52:
        verdict = "V4_SPREAD_PATCH_HELPS"
    elif parity["verdict"] in ("FEATURE_PARITY_CONFIRMED", "SPREAD_PROXY_FIXABLE"):
        verdict = "PARITY_OK_BIAS_IS_ROOT_CAUSE"
    else:
        verdict = "NEEDS_REVIEW"

    return {
        "now": NOW,
        "verdict": verdict,
        "parity": parity,
        "event_bias": bias,
        "dataset_v3_rows": len(v3),
        "dataset_v4_rows": len(v4),
        "retrain_v3": v3_eval,
        "retrain_v4": v4_eval,
        "comparison": {
            "test_pf_v3": test_pf_v3,
            "test_pf_v4": test_pf_v4,
            "test_auc_v4": test_auc_v4,
            "test_pf_delta": round(test_pf_v4 - test_pf_v3, 4),
        },
    }, v4


def write_all(data: dict, v4: pd.DataFrame) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if v4 is not None and not v4.empty:
        v4.to_parquet(ARTIFACTS / "dataset_v4_spread_patched.parquet", index=False)

    payloads = {
        "feature_parity_audit.json": data.get("parity", {}),
        "event_sampling_bias.json": data.get("event_bias", {}),
        "dataset_v4_build_report.json": {
            "timestamp_utc": data["now"],
            **{k: v for k, v in data.items() if k not in ("now", "parity", "event_bias")},
        },
        "phase42_final_report.json": {
            "phase": "42",
            "title": "Feature Parity + Spread Patch + Event Bias Audit",
            "timestamp_utc": data["now"],
            "verdict": data["verdict"],
            "parity_verdict": (data.get("parity") or {}).get("verdict"),
            "event_bias_verdict": (data.get("event_bias") or {}).get("verdict"),
            "dataset_v4_rows": data.get("dataset_v4_rows"),
            "comparison": data.get("comparison"),
            "deliverables": [
                "feature_parity_audit.json",
                "event_sampling_bias.json",
                "dataset_v4_build_report.json",
                "phase42_final_report.json",
                "tradingbot/ml/research/phase42/artifacts/dataset_v4_spread_patched.parquet",
            ],
        },
    }
    for name, payload in payloads.items():
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)


def main() -> None:
    data, v4_df = run_phase42()
    write_all(data, v4_df)
    print(json.dumps({
        "verdict": data["verdict"],
        "parity": (data.get("parity") or {}).get("verdict"),
        "bias": (data.get("event_bias") or {}).get("verdict"),
        "comparison": data.get("comparison"),
    }, indent=2))


if __name__ == "__main__":
    main()
