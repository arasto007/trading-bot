#!/usr/bin/env python3
"""PHASE 18B ? Regime-aware PA meta-labeler retraining (RESEARCH / SHADOW ONLY).

USE_ML_KERNEL stays false. No router or execution patch.
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

from tradingbot.ml.feature_store import FEATURES, InstitutionalFeatureStore
from tradingbot.research.pa_meta_retrain import (
    CALIBRATORS,
    META_THRESHOLD,
    REGIMES,
    train_regime,
)

SYMBOL = "XAUUSD"
LOOKBACK = 800
CACHE_180 = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
SRC_18A = ROOT / "data" / "ml" / "research" / "phase18a" / "labeled_setups_180d.parquet"
OUT_DIR = ROOT / "data" / "ml" / "research" / "phase18b"
FEAT_PATH = OUT_DIR / "pa_setups_featured.parquet"
MATRIX_PATH = ROOT / "logs" / "phase18b_meta_matrix.json"
CAL_PATH = ROOT / "logs" / "phase18b_calibration_report.json"
RESULT_PATH = ROOT / "logs" / "phase18b_meta_result.txt"


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def load_m5() -> pd.DataFrame:
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    df = pd.read_parquet(CACHE_180)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index("time")
        df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df["volume"] = df["tick_volume"]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    return prepare_indicator_frame(df[keep].dropna().sort_index())


def resample_h4(df: pd.DataFrame) -> pd.DataFrame:
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    agg = (
        df.resample("4h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    return prepare_indicator_frame(agg)


def build_featured() -> pd.DataFrame:
    if FEAT_PATH.is_file():
        feat = pd.read_parquet(FEAT_PATH)
        emit(f"loaded cached features {FEAT_PATH} rows={len(feat)}")
        return feat

    labeled = pd.read_parquet(SRC_18A)
    labeled = labeled[labeled["label"].isin([0, 1])].copy()
    emit(f"TASK features ? 18A binary setups n={len(labeled)}")
    df = load_m5()
    h4 = resample_h4(df)
    rows: list[dict[str, Any]] = []
    n = len(labeled)
    records = labeled.to_dict("records")
    for k, rec in enumerate(records, start=1):
        if k % 400 == 0:
            emit(f"  feature progress {k}/{n}")
        i = int(rec["bar_index"])
        if i < 60 or i >= len(df):
            continue
        start = max(0, i - LOOKBACK)
        window = df.iloc[start : i + 1]
        feats = InstitutionalFeatureStore.compute_at(
            window, len(window) - 1, symbol=SYMBOL, h4_df=h4, regime=str(rec["regime"])
        )
        merged = dict(rec)
        for name in FEATURES:
            merged[name] = feats.get(name)
        merged["regime"] = str(rec["regime"])
        rows.append(merged)

    feat = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    feat.to_parquet(FEAT_PATH, index=False)
    emit(f"saved {FEAT_PATH} rows={len(feat)}")
    return feat


def pick_global_best(packs: dict[str, Any]) -> dict[str, Any] | None:
    best = None
    best_key = None
    for regime, pack in packs.items():
        row = pack.get("best")
        if not row:
            continue
        m = row["metrics"]
        key = (
            1 if m.get("passed") else 0,
            1 if int(m.get("oos_trades") or 0) >= 10 else 0,
            float(m.get("oos_pf") or 0),
            float(m.get("oos_expectancy_r") or 0),
            -float(m.get("brier") or 1),
            -float(m.get("ece") or 1),
        )
        if best_key is None or key > best_key:
            best_key = key
            best = row
    return best


def calibrator_summary(packs: dict[str, Any]) -> dict[str, Any]:
    by_method: dict[str, list[dict[str, float]]] = {m: [] for m in CALIBRATORS}
    rows = []
    for regime, pack in packs.items():
        for model in pack.get("models") or []:
            for method, met in (model.get("calibrators") or {}).items():
                if not isinstance(met, dict) or "brier" not in met:
                    continue
                rec = {
                    "regime": regime,
                    "model_type": model["model_type"],
                    "method": method,
                    **{k: met[k] for k in met if k != "passed"},
                    "passed": bool(met.get("passed")),
                }
                rows.append(rec)
                by_method.setdefault(method, []).append(met)
    agg = {}
    for method, mets in by_method.items():
        if not mets:
            continue
        agg[method] = {
            "mean_brier": round(float(np.mean([m["brier"] for m in mets])), 6),
            "mean_ece": round(float(np.mean([m["ece"] for m in mets])), 6),
            "mean_pf": round(float(np.mean([m["oos_pf"] for m in mets])), 4),
            "n": len(mets),
        }
    best_method = None
    if agg:
        best_method = sorted(agg.items(), key=lambda kv: (kv[1]["mean_brier"], kv[1]["mean_ece"]))[0][0]
    return {"by_method": agg, "rows": rows, "best_method_by_brier": best_method}


def write_outputs(packs: dict[str, Any], feat: pd.DataFrame) -> None:
    best = pick_global_best(packs)
    cal = calibrator_summary(packs)
    ready = bool(best and best["metrics"].get("passed"))
    m = (best or {}).get("metrics") or {}
    zeros = {
        "oos_pf": 0.0,
        "oos_expectancy_r": 0.0,
        "precision_buy": 0.0,
        "precision_sell": 0.0,
        "brier": 1.0,
        "ece": 1.0,
        "psi": 1.0,
    }
    m = {**zeros, **m}

    matrix = {
        "phase": "18B",
        "mode": "RESEARCH_SHADOW_ONLY",
        "use_ml_kernel": False,
        "features": list(FEATURES),
        "feature_count": len(FEATURES),
        "threshold": META_THRESHOLD,
        "split": "train60_calib20_test20",
        "cv": "PurgedKFold embargo_bars=3",
        "class_weight": "balanced",
        "source": str(SRC_18A),
        "featured_rows": int(len(feat)),
        "binary_by_regime": {r: int((feat["regime"] == r).sum()) for r in REGIMES},
        "regimes": {
            r: {
                "samples": p.get("samples"),
                "n_train": p.get("n_train"),
                "n_calib": p.get("n_calib"),
                "n_test": p.get("n_test"),
                "skip": p.get("skip"),
                "models": p.get("models"),
                "best": p.get("best"),
            }
            for r, p in packs.items()
        },
        "best": best,
        "meta_institutional_ready": ready,
        "keep_shadow_mode": True,
        "patch_applied": False,
    }
    MATRIX_PATH.write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")

    cal_payload = {
        "phase": "18B",
        "methods": list(CALIBRATORS),
        "split": "calib_fit_on_20pct_eval_on_test20",
        **cal,
        "selected": {
            "regime": None if not best else best.get("regime"),
            "model": None if not best else best.get("model_type"),
            "calibrator": None if not best else best.get("calibrator"),
            "metrics": m,
        },
    }
    CAL_PATH.write_text(json.dumps(cal_payload, indent=2, default=str), encoding="utf-8")

    lines = [
        "PHASE_18B_RESULT",
        "",
        f"BEST_REGIME={best['regime'] if best else 'NONE'}",
        f"BEST_MODEL={best['model_type'] if best else 'NONE'}",
        f"BEST_CALIBRATOR={best['calibrator'] if best else 'NONE'}",
        "",
        f"OOS_PF={m['oos_pf']}",
        f"OOS_EXPECTANCY_R={m['oos_expectancy_r']}",
        f"PRECISION_BUY={m['precision_buy']}",
        f"PRECISION_SELL={m['precision_sell']}",
        f"BRIER={m['brier']}",
        f"ECE={m['ece']}",
        f"PSI={m['psi']}",
        "",
        f"META_INSTITUTIONAL_READY={'YES' if ready else 'NO'}",
        "KEEP_SHADOW_MODE=YES",
        "PATCH_APPLIED=NO",
        "",
        f"THRESHOLD={META_THRESHOLD}",
        f"FEATURED_BINARY={len(feat)}",
        "USE_ML_KERNEL=false",
        "MODE=RESEARCH_SHADOW_ONLY",
    ]
    for regime in REGIMES:
        pack = packs.get(regime) or {}
        lines.append(
            f"[{regime}] n={pack.get('samples')} train={pack.get('n_train')} "
            f"calib={pack.get('n_calib')} test={pack.get('n_test')} skip={pack.get('skip')}"
        )
        brow = pack.get("best")
        if brow:
            bm = brow["metrics"]
            lines.append(
                f"  BEST={brow['model_type']}/{brow['calibrator']} "
                f"PF={bm['oos_pf']} ExpR={bm['oos_expectancy_r']} "
                f"PBuy={bm['precision_buy']} PSell={bm['precision_sell']} "
                f"Brier={bm['brier']} ECE={bm['ece']} PSI={bm['psi']} "
                f"trades={bm['oos_trades']} PASS={bm['passed']}"
            )
        for model in pack.get("models") or []:
            for method in CALIBRATORS:
                met = (model.get("calibrators") or {}).get(method) or {}
                if "brier" not in met:
                    continue
                lines.append(
                    f"  {model['model_type']}/{method}: PF={met['oos_pf']} "
                    f"ExpR={met['oos_expectancy_r']} Brier={met['brier']} "
                    f"ECE={met['ece']} PBuy={met['precision_buy']} "
                    f"PSell={met['precision_sell']} trades={met['oos_trades']} "
                    f"PASS={met.get('passed')}"
                )
    text = "\n".join(lines) + "\n"
    RESULT_PATH.write_text(text, encoding="utf-8")
    emit(text)
    emit(f"WROTE {MATRIX_PATH}")
    emit(f"WROTE {CAL_PATH}")
    emit(f"WROTE {RESULT_PATH}")


def main() -> int:
    emit("PHASE 18B ? PA regime meta retraining (research/shadow only)")
    emit("USE_ML_KERNEL=false PATCH_APPLIED=NO")
    feat = build_featured()
    feat["regime"] = feat["regime"].astype(str).str.upper()
    packs: dict[str, Any] = {}
    for regime in REGIMES:
        sub = feat[feat["regime"] == regime].copy()
        emit(f"train {regime} n={len(sub)}")
        pack = train_regime(regime, sub, feature_cols=list(FEATURES), embargo_bars=3)
        packs[regime] = pack
        if pack.get("best"):
            b = pack["best"]
            emit(
                f"  best {b['model_type']}/{b['calibrator']} "
                f"PF={b['metrics']['oos_pf']} Brier={b['metrics']['brier']} "
                f"PASS={b['metrics']['passed']}"
            )
        else:
            emit(f"  skip={pack.get('skip')}")
    write_outputs(packs, feat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
