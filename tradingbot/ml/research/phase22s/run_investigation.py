#!/usr/bin/env python3
"""Phase 22S — FeatureBuilder numerical parity certification."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


def main() -> int:
    from tradingbot.ml.research.phase22s.parity_cert import (
        determine_verdict,
        diagnose_mismatch_reasons,
        find_minimum_history,
        run_parity_certification,
        run_window_sensitivity,
    )

    now = datetime.now(timezone.utc).isoformat()
    print("Running full dataset_v2 parity (5724 rows)...", flush=True)
    parity = run_parity_certification()
    parity["generated_utc"] = now

    print("Running structure_distance window sensitivity...", flush=True)
    window = run_window_sensitivity(sample_size=300)
    window["generated_utc"] = now

    min_hist = find_minimum_history(window, parity)
    min_hist["generated_utc"] = now

    fs = parity.get("feature_statistics") or {}
    verdict = determine_verdict(fs)
    diagnoses = diagnose_mismatch_reasons(parity, window)

    feature_statistics = {
        "phase": "22S",
        "generated_utc": now,
        "per_feature": fs,
        "diagnosis": diagnoses,
    }

    final = {
        "phase": "22S",
        "title": "FeatureBuilder Numerical Parity Certification",
        "generated_utc": now,
        "method": (
            "Reload dataset_v2 event rows; re-run FeatureBuilder.compute_at on CandleStore "
            "with identical SparseEventDatasetBuilder kwargs (h4, m15, spread_proxy); "
            "compare ema50_slope, candle_direction, structure_distance"
        ),
        "production_modified": False,
        "verdict": verdict,
        "rows_compared": parity.get("rows_compared"),
        "feature_statistics": fs,
        "diagnosis": diagnoses,
        "stable_window_structure_distance": window.get("stable_window_at_99pct"),
        "summary": _verdict_summary(verdict, fs, window),
    }

    _write("feature_value_parity.json", parity)
    _write("window_sensitivity.json", window)
    _write("feature_statistics.json", feature_statistics)
    _write("minimum_history_required.json", min_hist)
    _write("phase22s_final_report.json", final)

    print(json.dumps({"verdict": verdict, "stats": fs}, indent=2))
    return 0


def _verdict_summary(verdict: str, fs: dict, window: dict) -> str:
    parts = [f"Verdict={verdict}."]
    for f, s in fs.items():
        parts.append(f"{f}: exact_match={s.get('exact_match_pct')}% RMSE={s.get('rmse')}.")
    conv = window.get("convergence_summary") or {}
    if conv:
        parts.append(
            "structure_distance window match %: "
            + ", ".join(f"{k}={v.get('match_pct')}" for k, v in conv.items())
        )
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
