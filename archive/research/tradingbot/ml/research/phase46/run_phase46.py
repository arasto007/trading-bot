#!/usr/bin/env python3
"""Phase 46 — ML signal-aligned dataset v6 (production population)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase46" / "artifacts"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def run_phase46_async() -> tuple[dict, pd.DataFrame]:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase36.retrain_validation import train_eval_chronological
    from tradingbot.ml.research.phase46.ml_signal_dataset import (
        build_ml_signal_dataset,
        collect_ml_signals_multi,
    )

    force = os.environ.get("PHASE46_FORCE", "").lower() in ("1", "true", "yes")
    signals = await collect_ml_signals_multi(("A", "B", "C", "H"), force=force)
    v6 = build_ml_signal_dataset(signals)

    if v6.empty or len(v6) < 50:
        return {
            "verdict": "INSUFFICIENT_ML_SIGNALS",
            "signals_collected": len(signals),
            "rows_built": len(v6),
        }, v6

    feats = feature_columns(v6)
    eval_v6 = train_eval_chronological(v6, "label_v3", feats)
    test_pf = (eval_v6.get("test") or {}).get("pf", 0)
    test_auc = (eval_v6.get("test") or {}).get("auc", 0)

    by_source = v6.groupby("source_dataset").size().to_dict() if "source_dataset" in v6 else {}
    buy_pct = round(float((v6["direction"] == 1).mean()) * 100, 2)

    if test_pf >= 1.3 and test_auc >= 0.55:
        verdict = "ML_SIGNAL_DATASET_PROMISING"
    elif test_pf >= 1.0:
        verdict = "ML_SIGNAL_DATASET_MARGINAL"
    elif len(v6) >= 200:
        verdict = "ML_SIGNAL_POPULATION_CAPTURED"
    else:
        verdict = "ML_SIGNAL_INSUFFICIENT"

    return {
        "now": NOW,
        "verdict": verdict,
        "signals_collected": len(signals),
        "dataset_v6_rows": len(v6),
        "buy_direction_pct": buy_pct,
        "rows_by_source_dataset": {str(k): int(v) for k, v in by_source.items()},
        "retrain_v6": eval_v6,
        "comparison": {
            "test_pf_v6": test_pf,
            "test_auc_v6": test_auc,
            "phase45_structure_rows": 403,
        },
    }, v6


def run_phase46() -> tuple[dict, pd.DataFrame]:
    return asyncio.run(run_phase46_async())


def write_all(data: dict, v6: pd.DataFrame) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not v6.empty:
        v6.to_parquet(ARTIFACTS / "dataset_v6_ml_signals.parquet", index=False)

    payloads = {
        "ml_signal_capture_report.json": {
            "timestamp_utc": data["now"],
            **{k: v for k, v in data.items() if k != "now"},
        },
        "phase46_final_report.json": {
            "phase": "46",
            "title": "ML Signal-Aligned Dataset V6",
            "timestamp_utc": data["now"],
            "verdict": data["verdict"],
            "dataset_v6_rows": data.get("dataset_v6_rows"),
            "signals_collected": data.get("signals_collected"),
            "rows_by_source_dataset": data.get("rows_by_source_dataset"),
            "comparison": data.get("comparison"),
            "deliverables": [
                "ml_signal_capture_report.json",
                "phase46_final_report.json",
                "tradingbot/ml/research/phase46/artifacts/dataset_v6_ml_signals.parquet",
            ],
        },
    }
    for name, payload in payloads.items():
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)


def main() -> None:
    data, v6_df = run_phase46()
    write_all(data, v6_df)
    print(json.dumps({
        "verdict": data["verdict"],
        "rows": data.get("dataset_v6_rows"),
        "signals": data.get("signals_collected"),
    }, indent=2))


if __name__ == "__main__":
    main()
