#!/usr/bin/env python3
"""Phase 45 — Structure-event dataset v5 + label quality audit."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase45" / "artifacts"
V4_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase42" / "artifacts" / "dataset_v4_spread_patched.parquet"
V3_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase39" / "artifacts" / "dataset_v3_expanded.parquet"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_base() -> pd.DataFrame | None:
    if V4_PATH.is_file():
        return pd.read_parquet(V4_PATH)
    if V3_PATH.is_file():
        return pd.read_parquet(V3_PATH)
    return None


def run_phase45() -> tuple[dict, pd.DataFrame]:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase36.retrain_validation import train_eval_chronological
    from tradingbot.ml.research.phase45.structure_dataset import filter_structure_rows, label_audit_by_event

    base = _load_base()
    if base is None or base.empty:
        return {"verdict": "INSUFFICIENT_DATA"}, pd.DataFrame()

    v5 = filter_structure_rows(base)
    if len(v5) < 100:
        return {"verdict": "INSUFFICIENT_STRUCTURE_ROWS", "rows": len(v5)}, v5

    audit = label_audit_by_event(v5, label_col="label_v3")
    feats = feature_columns(v5)
    eval_v5 = train_eval_chronological(v5, "label_v3", feats)

    test_pf = (eval_v5.get("test") or {}).get("pf", 0)
    test_auc = (eval_v5.get("test") or {}).get("auc", 0)
    dom_share = round(len(v5[v5["event_type"] == "trading_session"]) / len(v5) * 100, 2)

    if test_pf >= 1.3 and test_auc >= 0.55:
        verdict = "STRUCTURE_LABELS_PROMISING"
    elif test_pf >= 1.0 and test_auc >= 0.52:
        verdict = "STRUCTURE_LABELS_MARGINAL"
    elif test_pf > 0.73:
        verdict = "STRUCTURE_IMPROVES_OVER_SESSION_MIX"
    else:
        verdict = "STRUCTURE_INSUFFICIENT"

    return {
        "now": NOW,
        "verdict": verdict,
        "dataset_v5_rows": len(v5),
        "trading_session_share_pct": dom_share,
        "label_audit_by_event": audit,
        "retrain_v5": eval_v5,
        "comparison_vs_v4_full": {
            "rows_v4": len(base),
            "rows_v5": len(v5),
            "row_reduction_pct": round((1 - len(v5) / len(base)) * 100, 2),
            "test_pf_v5": test_pf,
            "test_auc_v5": test_auc,
        },
    }, v5


def write_all(data: dict, v5: pd.DataFrame) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not v5.empty:
        v5.to_parquet(ARTIFACTS / "dataset_v5_structure.parquet", index=False)

    payloads = {
        "structure_label_audit.json": {
            "timestamp_utc": data["now"],
            "verdict": data["verdict"],
            "label_audit_by_event": data.get("label_audit_by_event"),
            "dataset_v5_rows": data.get("dataset_v5_rows"),
        },
        "dataset_v5_build_report.json": {
            "timestamp_utc": data["now"],
            **{k: v for k, v in data.items() if k != "now"},
        },
        "phase45_final_report.json": {
            "phase": "45",
            "title": "Structure-Event Dataset V5",
            "timestamp_utc": data["now"],
            "verdict": data["verdict"],
            "dataset_v5_rows": data.get("dataset_v5_rows"),
            "comparison_vs_v4_full": data.get("comparison_vs_v4_full"),
            "deliverables": [
                "structure_label_audit.json",
                "dataset_v5_build_report.json",
                "phase45_final_report.json",
                "tradingbot/ml/research/phase45/artifacts/dataset_v5_structure.parquet",
            ],
        },
    }
    for name, payload in payloads.items():
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)


def main() -> None:
    data, v5_df = run_phase45()
    write_all(data, v5_df)
    print(json.dumps({"verdict": data["verdict"], "rows": data.get("dataset_v5_rows")}, indent=2))


if __name__ == "__main__":
    main()
