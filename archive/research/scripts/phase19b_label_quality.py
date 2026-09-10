#!/usr/bin/env python3
"""PHASE 19B ? Institutional ML label quality upgrade (research only).

Multi-horizon labels, soft timeout conversion, triple-class dataset.
Does not overwrite Phase 18A files. Does not enable live ML.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
    "TRADINGBOT_DRY_RUN": "1",
})
warnings.filterwarnings("ignore")

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

SRC_18A = ROOT / "data" / "ml" / "research" / "phase18a" / "labeled_setups_180d.parquet"
CACHE_180 = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
OUT_DIR = ROOT / "data" / "ml" / "research" / "phase19b"
LOG_DIR = ROOT / "logs" / "phase19b"
MULTI_PATH = OUT_DIR / "labeled_setups_multi_horizon.parquet"
TRIPLE_PATH = OUT_DIR / "triple_class_dataset.parquet"
RESULT = LOG_DIR / "phase19b_result.txt"
SUMMARY = LOG_DIR / "phase19b_label_summary.json"

HORIZONS = (("h12", 12), ("h24", 24), ("h48", 48))
SOFT_WIN_MFE = 0.8
SOFT_WIN_MAE = 0.5
SOFT_LOSS_MFE = 0.2
SOFT_LOSS_MAE = 0.8
HIGH_CONF_MIN = 0.50


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def load_m5() -> pd.DataFrame:
    df = pd.read_parquet(CACHE_180)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index("time")
        df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.rename(columns={c: c.lower() for c in df.columns}).sort_index()


def path_label(
    highs: np.ndarray,
    lows: np.ndarray,
    i: int,
    direction: int,
    entry: float,
    sl: float,
    tp: float,
    horizon: int,
) -> dict[str, Any]:
    risk = abs(entry - sl)
    n = len(highs)
    start = i + 1
    end = min(n, i + 1 + horizon)
    if risk <= 0 or start >= n:
        return {
            "outcome": "timeout",
            "mfe_r": 0.0,
            "mae_r": 0.0,
            "bars_to_outcome": None,
        }
    mfe = mae = 0.0
    outcome = "timeout"
    bars = end - i
    for j in range(start, end):
        hi = float(highs[j])
        lo = float(lows[j])
        if direction > 0:
            mfe = max(mfe, max(0.0, (hi - entry) / risk))
            mae = max(mae, max(0.0, (entry - lo) / risk))
            hit_sl = lo <= sl
            hit_tp = hi >= tp
        else:
            mfe = max(mfe, max(0.0, (entry - lo) / risk))
            mae = max(mae, max(0.0, (hi - entry) / risk))
            hit_sl = hi >= sl
            hit_tp = lo <= tp
        k = j - i
        if hit_sl and hit_tp:
            outcome, bars = "sl_first", k
            break
        if hit_sl:
            outcome, bars = "sl_first", k
            break
        if hit_tp:
            outcome, bars = "tp_first", k
            break
    return {
        "outcome": outcome,
        "mfe_r": round(float(mfe), 4),
        "mae_r": round(float(mae), 4),
        "bars_to_outcome": int(bars) if outcome != "timeout" else None,
    }


def apply_soft(outcome: str, mfe: float, mae: float) -> str:
    if outcome != "timeout":
        return outcome
    if mfe >= SOFT_WIN_MFE and mae <= SOFT_WIN_MAE:
        return "soft_win"
    if mfe <= SOFT_LOSS_MFE and mae >= SOFT_LOSS_MAE:
        return "soft_loss"
    return "timeout"


def to_class(soft_outcome: str) -> int:
    if soft_outcome in ("tp_first", "soft_win"):
        return 1
    if soft_outcome in ("sl_first", "soft_loss"):
        return 0
    return 2


def class_name(c: int) -> str:
    return {1: "strong_win", 0: "strong_loss", 2: "ambiguous"}[int(c)]


def main() -> int:
    emit("PHASE 19B ? label quality upgrade (research only)")
    src = pd.read_parquet(SRC_18A)
    emit(f"loaded 18A labeled n={len(src)} (read-only)")
    original_timeout = float((src["label"] == -1).mean() * 100.0)

    df = load_m5()
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    n = len(src)
    emit(f"relabeling {n} setups at H12/H24/H48")

    extra: dict[str, list[Any]] = {}
    for prefix, _h in HORIZONS:
        for col in (f"{prefix}_outcome", f"{prefix}_soft", f"{prefix}_class",
                    f"{prefix}_mfe_r", f"{prefix}_mae_r", f"{prefix}_bars"):
            extra[col] = []

    for k, row in enumerate(src.itertuples(index=False), start=1):
        if k % 2000 == 0:
            emit(f"  progress {k}/{n}")
        i = int(row.bar_index)
        direction = int(row.direction_int)
        entry = float(row.entry_price)
        sl = float(row.stop_price)
        tp = float(row.tp_price)
        for prefix, horizon in HORIZONS:
            info = path_label(highs, lows, i, direction, entry, sl, tp, horizon)
            soft = apply_soft(info["outcome"], info["mfe_r"], info["mae_r"])
            extra[f"{prefix}_outcome"].append(info["outcome"])
            extra[f"{prefix}_soft"].append(soft)
            extra[f"{prefix}_class"].append(to_class(soft))
            extra[f"{prefix}_mfe_r"].append(info["mfe_r"])
            extra[f"{prefix}_mae_r"].append(info["mae_r"])
            extra[f"{prefix}_bars"].append(info["bars_to_outcome"])

    out = src.copy()
    for col, vals in extra.items():
        out[col] = vals

    out["label_class"] = out["h24_class"].astype(int)
    out["label_name"] = out["label_class"].map(class_name)
    out["h24_timeout_hard"] = out["h24_outcome"] == "timeout"
    out["h24_timeout_after_soft"] = out["h24_soft"] == "timeout"

    same_12_24 = (out["h12_class"] == out["h24_class"]).astype(float)
    same_24_48 = (out["h24_class"] == out["h48_class"]).astype(float)
    out["h12_h24_match"] = same_12_24.astype(bool)
    out["h24_h48_match"] = same_24_48.astype(bool)
    out["label_stability_score"] = ((same_12_24 + same_24_48) / 2.0).round(4)

    reclaim = out["reclaim"].astype(float) if "reclaim" in out.columns else 0.0
    bos = out["bos"].astype(float) if "bos" in out.columns else 0.0
    disp = out["displacement_score"].astype(float) if "displacement_score" in out.columns else 0.0
    disp_n = np.clip(disp / 100.0, 0.0, 1.0)
    mfe = out["h24_mfe_r"].astype(float)
    mfe_q = np.clip(mfe / 1.5, 0.0, 1.0)
    out["reclaim_success"] = reclaim
    out["bos_strength"] = bos
    out["displacement_score_norm"] = disp_n.round(4)
    out["mfe_quality"] = mfe_q.round(4)
    out["confidence_weight"] = (
        0.4 * reclaim + 0.2 * bos + 0.2 * disp_n + 0.2 * mfe_q
    ).clip(0.0, 1.0).round(4)
    out["high_confidence"] = out["confidence_weight"] >= HIGH_CONF_MIN

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(MULTI_PATH, index=False)
    triple_cols = [
        c for c in out.columns
        if c not in ("tel_dec_event", "tel_hold_event")
    ]
    out[triple_cols].to_parquet(TRIPLE_PATH, index=False)
    emit(f"saved {MULTI_PATH} rows={len(out)}")
    emit(f"saved {TRIPLE_PATH}")

    new_timeout = float(out["h24_timeout_after_soft"].mean() * 100.0)
    sw = int((out["label_class"] == 1).sum())
    sl = int((out["label_class"] == 0).sum())
    amb = int((out["label_class"] == 2).sum())
    st_12 = float(same_12_24.mean())
    st_24 = float(same_24_48.mean())
    mean_w = float(out["confidence_weight"].mean())
    high_n = int(out["high_confidence"].sum())
    grade = bool(new_timeout < 25.0 and high_n > 3000 and st_24 > 0.70)

    payload = {
        "original_timeout_pct": round(original_timeout, 4),
        "new_timeout_pct_h24_after_soft": round(new_timeout, 4),
        "h48_timeout_after_soft_pct": round(float((out["h48_soft"] == "timeout").mean() * 100.0), 4),
        "strong_win": sw,
        "strong_loss": sl,
        "ambiguous": amb,
        "h12_h24_stability": round(st_12, 4),
        "h24_h48_stability": round(st_24, 4),
        "mean_confidence_weight": round(mean_w, 4),
        "high_confidence_samples": high_n,
        "high_confidence_threshold": HIGH_CONF_MIN,
        "soft_win_h24": int((out["h24_soft"] == "soft_win").sum()),
        "soft_loss_h24": int((out["h24_soft"] == "soft_loss").sum()),
        "dataset_ml_grade": grade,
        "source_18a": str(SRC_18A),
        "overwrote_18a": False,
    }
    SUMMARY.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "PHASE_19B_RESULT",
        "",
        f"ORIGINAL_TIMEOUT_PCT={original_timeout:.2f}",
        f"NEW_TIMEOUT_PCT={new_timeout:.2f}",
        "",
        f"STRONG_WIN_COUNT={sw}",
        f"STRONG_LOSS_COUNT={sl}",
        f"AMBIGUOUS_COUNT={amb}",
        "",
        f"H12_H24_STABILITY={st_12:.4f}",
        f"H24_H48_STABILITY={st_24:.4f}",
        "",
        f"MEAN_CONFIDENCE_WEIGHT={mean_w:.4f}",
        f"HIGH_CONFIDENCE_SAMPLES={high_n}",
        "",
        f"DATASET_ML_GRADE={'YES' if grade else 'NO'}",
        "PATCH_APPLIED=NO",
        "",
        f"H24_SOFT_WIN={payload['soft_win_h24']}",
        f"H24_SOFT_LOSS={payload['soft_loss_h24']}",
        f"H48_TIMEOUT_AFTER_SOFT_PCT={payload['h48_timeout_after_soft_pct']:.2f}",
        f"PRIMARY_HORIZON=H24",
        "OVERWROTE_PHASE18A=NO",
        "USE_ML_KERNEL=false",
        "MODE=RESEARCH_ONLY",
    ]
    text = "\n".join(lines) + "\n"
    RESULT.write_text(text, encoding="utf-8")
    emit(text)
    emit(f"WROTE {RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
