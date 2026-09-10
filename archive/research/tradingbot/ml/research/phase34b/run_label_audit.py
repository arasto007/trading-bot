#!/usr/bin/env python3
"""Phase 34B — Dataset Label Truth Audit (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_dataset_v2(symbol: str = "XAUUSD", timeframe: str = "M5") -> pd.DataFrame | None:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.dataset.store import DatasetStore

    base = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    store = DatasetStore(base)
    df = store.load_v2(symbol, timeframe)
    if df is None or df.empty:
        df = store.load(symbol, timeframe)
    return df


def _label_replay_consistency(df: pd.DataFrame, sample_n: int = 200) -> dict:
    """Check stored labels vs forward TP/SL resolution on sample rows."""
    from tradingbot.ml.dataset.labels import label_from_future_candles
    import asyncio
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.phase22f.config import build_dataset

    if "label" not in df.columns or "timestamp" not in df.columns:
        return {"error": "missing columns", "checked": 0}

    ds = build_dataset("A")
    ohlcv = asyncio.run(load_ohlcv_for_dataset(ds, "M5"))
    if ohlcv is None or ohlcv.empty:
        return {"error": "no_ohlcv", "checked": 0}

    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        ohlcv = ohlcv.set_index("timestamp")
    ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    sample = work.sample(n=min(sample_n, len(work)), random_state=42) if len(work) > sample_n else work

    matches = mismatches = 0
    mismatch_examples: list[dict] = []
    for _, row in sample.iterrows():
        ts = row["timestamp"]
        idx = int(ohlcv.index.searchsorted(ts))
        if idx >= len(ohlcv) - 10:
            continue
        direction = 1
        if "direction" in row and row["direction"] is not None:
            direction = 1 if int(row["direction"]) > 0 else -1
        elif "signal" in row and row["signal"] is not None:
            sig = str(row["signal"]).upper()
            direction = 1 if sig == "BUY" else (-1 if sig == "SELL" else 0)
        if direction == 0:
            continue
        try:
            recomputed = label_from_future_candles(ohlcv, idx, direction=direction)
            stored = int(row["label"])
            if int(recomputed.label) == stored:
                matches += 1
            else:
                mismatches += 1
                if len(mismatch_examples) < 5:
                    mismatch_examples.append({
                        "timestamp": str(ts),
                        "stored": stored,
                        "recomputed": int(recomputed.label),
                    })
        except Exception:
            continue

    checked = matches + mismatches
    return {
        "checked": checked,
        "matches": matches,
        "mismatches": mismatches,
        "match_pct": round(matches / max(checked, 1) * 100, 2),
        "mismatch_examples": mismatch_examples,
    }


def run_audit() -> dict:
    from tradingbot.ml.dataset.label_quality import LabelQualityValidator
    from tradingbot.ml.dataset.schema import Label

    df = _load_dataset_v2()
    if df is None or df.empty:
        return {"verdict": "INSUFFICIENT_DATA", "error": "dataset not found"}

    validator = LabelQualityValidator()
    quality = validator.validate(df)

    n = len(df)
    labels = df["label"].astype(int) if "label" in df.columns else pd.Series(dtype=int)
    tp = int((labels == int(Label.TP_FIRST)).sum())
    sl = int((labels == int(Label.SL_FIRST)).sum())
    unresolved = n - tp - sl

    ts_col = pd.to_datetime(df["timestamp"], utc=True) if "timestamp" in df.columns else None
    chronological = True
    if ts_col is not None:
        chronological = bool(ts_col.is_monotonic_increasing)

    replay_check = _label_replay_consistency(df)

    label_win_rate = round(tp / max(tp + sl, 1) * 100, 2)
    verdict = "LABELS_VALID"
    issues: list[str] = []
    if quality.status == "fail":
        verdict = "LABELS_INVALID"
        issues.extend(quality.issues)
    if quality.class_imbalance_warnings:
        issues.extend(quality.class_imbalance_warnings)
    if not chronological:
        verdict = "LABELS_INVALID"
        issues.append("timestamps not chronological")
    if replay_check.get("match_pct", 100) < 95:
        verdict = "LABELS_NEEDS_REVIEW"
        issues.append(f"label replay mismatch {100 - replay_check.get('match_pct', 0):.1f}%")

    session_bias = {
        "possible_session_bias": quality.possible_session_bias,
        "dominant_session": quality.dominant_session,
    }
    direction_bias = quality.direction_bias

    return {
        "now": NOW,
        "verdict": verdict,
        "dataset_rows": n,
        "label_distribution": {
            "tp_first": tp,
            "sl_first": sl,
            "unresolved": unresolved,
            "label_win_rate_pct": label_win_rate,
        },
        "quality_report": quality.to_dict(),
        "chronological": chronological,
        "replay_consistency": replay_check,
        "session_bias": session_bias,
        "direction_bias": direction_bias,
        "issues": issues,
    }


def write_all(data: dict) -> None:
    def w(name: str, payload: dict) -> None:
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    w("label_quality_audit.json", {"timestamp_utc": data["now"], **data})
    w("phase34b_final_report.json", {
        "phase": "34B",
        "title": "Dataset Label Truth Audit",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "dataset_rows": data["dataset_rows"],
        "label_distribution": data["label_distribution"],
        "replay_consistency": data["replay_consistency"],
        "issues": data["issues"],
        "deliverables": ["label_quality_audit.json", "phase34b_final_report.json"],
    })


def main() -> None:
    data = run_audit()
    write_all(data)
    print(json.dumps({"verdict": data["verdict"], "rows": data["dataset_rows"]}, indent=2))


if __name__ == "__main__":
    main()
