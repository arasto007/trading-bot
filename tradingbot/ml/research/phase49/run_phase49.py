#!/usr/bin/env python3
"""Phase 49 — Fix bar index + expand ML capture 2021-2026."""

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
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def run_phase49_async() -> tuple[dict, pd.DataFrame]:
    from tradingbot.ml.research.phase36.retrain_validation import train_eval_chronological
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase49.ml_capture import build_ml_signal_dataset_v7, collect_all_signals

    skip = os.environ.get("PHASE49_SKIP_COLLECT", "").lower() in ("1", "true", "yes")
    force = os.environ.get("PHASE49_FORCE", "").lower() in ("1", "true", "yes")
    skip_legacy = os.environ.get("PHASE49_SKIP_LEGACY", "").lower() in ("1", "true", "yes")
    year_start = int(os.environ.get("PHASE49_YEAR_START", "2021"))
    year_end = int(os.environ.get("PHASE49_YEAR_END", "2026"))

    if skip:
        from tradingbot.ml.research.phase46.ml_signal_dataset import load_cached_signals

        labels = ["A", "B", "C", "H"]
        signals = []
        for label in labels:
            cached = load_cached_signals(label)
            if cached:
                for sig in cached.get("signals", []):
                    rec = dict(sig)
                    rec["source_dataset"] = label
                    signals.append(rec)
    else:
        signals = await collect_all_signals(
            use_cache=not force,
            force=force,
            include_legacy=not skip_legacy,
            year_start=year_start,
            year_end=year_end,
        )

    v7 = build_ml_signal_dataset_v7(signals)
    if v7.empty or len(v7) < 100:
        return {
            "verdict": "INSUFFICIENT_DATA",
            "signals_collected": len(signals),
            "rows_built": len(v7),
            "bar_index_fix": "timestamp_resolved_absolute_index",
        }, v7

    feats = feature_columns(v7)
    eval_v7 = train_eval_chronological(v7, "label_v3", feats)
    test_pf = (eval_v7.get("test") or {}).get("pf", 0)
    test_auc = (eval_v7.get("test") or {}).get("auc", 0)

    ts = pd.to_datetime(v7["timestamp"], utc=True)
    year_counts = {int(k): int(v) for k, v in ts.dt.year.value_counts().sort_index().items()}

    if len(year_counts) >= 4 and test_auc >= 0.52:
        verdict = "V7_MULTI_YEAR_CAPTURED"
    elif len(v7) >= 3000:
        verdict = "V7_FIXED_INDEX_CAPTURED"
    else:
        verdict = "V7_INSUFFICIENT"

    return {
        "now": NOW,
        "verdict": verdict,
        "bar_index_fix": "timestamp_resolved_absolute_index",
        "signals_collected": len(signals),
        "dataset_v7_rows": len(v7),
        "year_distribution": year_counts,
        "years_covered": len(year_counts),
        "retrain_v7": eval_v7,
        "comparison_vs_v6_buggy": {
            "v6_rows": 3827,
            "test_pf_v7": test_pf,
            "test_auc_v7": test_auc,
        },
    }, v7


def run_phase49() -> tuple[dict, pd.DataFrame]:
    return asyncio.run(run_phase49_async())


def write_all(data: dict, v7: pd.DataFrame) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not v7.empty:
        v7.to_parquet(ARTIFACTS / "dataset_v7_ml_signals.parquet", index=False)

    for name, payload in {
        "bar_index_fix_report.json": {
            "timestamp_utc": data["now"],
            "fix": data.get("bar_index_fix"),
            "v6_bug": "bar_index was slice-relative not global on fullest candles",
            "v7_resolution": "timestamp searchsorted on fullest candle store",
        },
        "dataset_v7_build_report.json": {k: v for k, v in data.items() if k != "now"},
        "phase49_final_report.json": {
            "phase": "49",
            "title": "Fixed Bar Index + Expanded ML Capture",
            "timestamp_utc": data["now"],
            "verdict": data["verdict"],
            "dataset_v7_rows": data.get("dataset_v7_rows"),
            "years_covered": data.get("years_covered"),
            "year_distribution": data.get("year_distribution"),
            "comparison_vs_v6_buggy": data.get("comparison_vs_v6_buggy"),
        },
    }.items():
        (ARTIFACTS / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)


def main() -> None:
    data, v7 = run_phase49()
    write_all(data, v7)
    print(json.dumps({
        "verdict": data["verdict"],
        "rows": data.get("dataset_v7_rows"),
        "years": data.get("years_covered"),
    }, indent=2))


if __name__ == "__main__":
    main()
