#!/usr/bin/env python3
"""Phase 50 — Strict multi-year walk-forward gate on v7."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"
V6_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase46" / "artifacts" / "dataset_v6_ml_signals.parquet"


def run_phase50() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase50.strict_walk_forward import strict_walk_forward

    path = V7_PATH if V7_PATH.is_file() else V6_PATH
    tag = "v7" if path == V7_PATH else "v6_fallback"
    if not path.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "run phase49 first"}

    df = pd.read_parquet(path)
    feats = feature_columns(df)
    strict = strict_walk_forward(df, "label_v3", feats)

    return {
        "now": NOW,
        "dataset": tag,
        "rows": len(df),
        "phase47_mean_pf": 1.5333,
        "phase47_caveat": "v6 used slice-relative bar_index — invalidated",
        **strict,
    }


def main() -> None:
    data = run_phase50()
    (ROOT / "phase50_final_report.json").write_text(
        json.dumps({"phase": "50", "title": "Strict Multi-Year Walk-Forward Gate", **data}, indent=2, default=str),
        encoding="utf-8",
    )
    (ROOT / "strict_walk_forward_gate.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase50_final_report.json", flush=True)
    print(json.dumps({
        "verdict": data["verdict"],
        "gate_passed": data.get("gate_passed"),
        "mean_pf": data.get("mean_pf"),
        "mean_auc": data.get("mean_auc"),
        "windows": len(data.get("walk_forward_windows", [])),
    }, indent=2))


if __name__ == "__main__":
    main()
