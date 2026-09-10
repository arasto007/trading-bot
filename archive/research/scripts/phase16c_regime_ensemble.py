#!/usr/bin/env python3
"""PHASE 16C — Regime-Aware ML Ensemble runner (research only)."""
from __future__ import annotations

import json
import os
import sys
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.research.regime_ensemble import (
    DECISION_THRESHOLD,
    FEATURE_COLS,
    REGIMES,
    ece_mce,
    predict_ensemble,
    predict_single,
    trade_metrics,
    train_regime_models,
)

DATA_DIR = ROOT / "data" / "ml" / "research" / "phase13d"
OUT_TXT = ROOT / "logs" / "phase16c_regime_ensemble_result.txt"
OUT_JSON = ROOT / "logs" / "phase16c_regime_ensemble_matrix.json"


def load_regime_df(regime: str) -> pd.DataFrame:
    path = DATA_DIR / f"dataset_{regime.lower()}.parquet"
    df = pd.read_parquet(path)
    # normalize direction
    if "direction" in df.columns:
        df["direction"] = df["direction"].astype(str).str.upper()
    return df


def load_replay_90d() -> pd.DataFrame:
    feat = pd.read_parquet(DATA_DIR / "pa_setups_featured.parquet")
    feat = feat[feat["label"].isin([0, 1])].copy()
    feat["timestamp_utc"] = pd.to_datetime(feat["timestamp_utc"], utc=True, format="mixed")
    # prefer source_window_days == 90; else last 90 calendar days
    if "source_window_days" in feat.columns and (feat["source_window_days"] == 90).any():
        sub = feat[feat["source_window_days"] == 90].copy()
    else:
        tmax = feat["timestamp_utc"].max()
        sub = feat[feat["timestamp_utc"] >= (tmax - pd.Timedelta(days=90))].copy()
    sub["direction"] = sub["direction"].astype(str).str.upper()
    sub["regime"] = sub["regime"].astype(str).str.upper()
    return sub.sort_values("timestamp_utc").reset_index(drop=True)


def apply_cooldown(df: pd.DataFrame, accept_mask: np.ndarray, cd_bars: int = 18, max_day: int = 3) -> list[float]:
    """Return realized R list for accepted trades with cooldown/day caps."""
    rs = []
    last_i = -10_000
    day_counts: Counter[str] = Counter()
    for i, row in df.iterrows():
        if not accept_mask[i]:
            continue
        # approximate bar spacing via index order
        if i - last_i < cd_bars:
            continue
        day = str(pd.Timestamp(row["timestamp_utc"]).date())
        if day_counts[day] >= max_day:
            continue
        rs.append(float(row["realized_r_multiple"]))
        last_i = i
        day_counts[day] += 1
    return rs


def meta_gate(df: pd.DataFrame) -> np.ndarray:
    """PA + Meta proxy: quality_score gate aligned to production MIN_QUALITY/meta scale."""
    q = df["quality_score"].astype(float).values
    # quality often 0-1 or 0-100
    qn = np.where(q > 1.5, q / 100.0, q)
    # meta threshold 0.38 on quality proxy + min conf 0.52 on quality
    return (qn >= 0.38) & (qn >= 0.52 * 0.7)  # soft: quality passes institutional band


def eval_path(name: str, df: pd.DataFrame, accept: np.ndarray) -> dict[str, Any]:
    rs = apply_cooldown(df, accept)
    tm = trade_metrics(rs)
    pf = tm["oos_pf"]
    out = {
        "path": name,
        "accepted_raw": int(accept.sum()),
        "trades": tm["trades"],
        "pf": tm["oos_pf"],
        "expectancy_r": tm["oos_expectancy_r"],
        "win_rate": round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 2) if rs else 0.0,
    }
    return out


def main() -> int:
    warnings.filterwarnings("ignore")
    print("PHASE 16C Regime-Aware ML Ensemble (research only)", flush=True)

    packs: dict[str, Any] = {}
    matrix: dict[str, Any] = {"regimes": {}, "feature_cols": FEATURE_COLS}

    for regime in REGIMES:
        df = load_regime_df(regime)
        print(f"train {regime} n={len(df)}", flush=True)
        pack = train_regime_models(regime, df, feature_cols=FEATURE_COLS)
        packs[regime] = pack
        matrix["regimes"][regime] = {
            "samples": pack["samples"],
            "models": pack["models"],
            "best": pack["best"],
        }
        for m in pack["models"]:
            met = m["metrics"]
            print(
                f"  {m['model_type']}: PF={met['oos_pf']} ExpR={met['oos_expectancy_r']} "
                f"Brier={met['brier']} ECE={met['ece']} w={m['weight']:.4f}",
                flush=True,
            )

    # Best single across all
    best_single = None
    best_key = (-1e9, -1e9, 1e9)
    best_regime = None
    for regime, pack in packs.items():
        if not pack["best"]:
            continue
        m = pack["best"]["metrics"]
        key = (1 if m.get("oos_trades", 0) >= 5 else 0, m["oos_pf"], m["oos_expectancy_r"], -m["brier"])
        if key > best_key:
            best_key = key
            best_single = pack["best"]["model_type"]
            best_regime = regime

    # Ensemble OOF diagnostics (concat regimes using each regime's OOF ensemble)
    ens_y = []
    ens_p = []
    ens_r = []
    for regime, pack in packs.items():
        frame = pack["frame"]
        fitted = pack["fitted"]
        if not fitted:
            continue
        # rebuild OOF ensemble from stored oof_prob per model
        n = len(frame)
        acc = np.zeros(n)
        wsum = 0.0
        mask_all = np.zeros(n, dtype=bool)
        for mt, mp in fitted.items():
            msk = mp["oof_mask"]
            oof = np.full(n, np.nan)
            oof[msk] = mp["oof_prob"]
            w = mp["weight"]
            acc = np.where(np.isfinite(oof), acc + w * oof, acc)
            wsum_mask = np.isfinite(oof)
            mask_all |= wsum_mask
        # weights already normalized
        p = acc
        y = frame["label"].astype(int).values
        r = frame["realized_r_multiple"].astype(float).values
        m = mask_all & np.isfinite(p)
        ens_y.extend(y[m].tolist())
        ens_p.extend(p[m].tolist())
        ens_r.extend(r[m].tolist())

    ens_y_a = np.asarray(ens_y, dtype=int)
    ens_p_a = np.clip(np.asarray(ens_p, dtype=float), 0, 1)
    from sklearn.metrics import brier_score_loss

    ens_brier = float(brier_score_loss(ens_y_a, ens_p_a)) if len(ens_y_a) else 1.0
    ens_ece, ens_mce = ece_mce(ens_y_a, ens_p_a) if len(ens_y_a) else (1.0, 1.0)
    taken = [float(r) for p, r in zip(ens_p_a, ens_r) if p >= DECISION_THRESHOLD]
    ens_tm = trade_metrics(taken)
    # PSI: mean of regime best model PSI
    ens_psi = float(
        np.mean(
            [
                packs[r]["best"]["metrics"]["psi_vs_train"]
                for r in packs
                if packs[r].get("best")
            ]
        )
    ) if any(packs[r].get("best") for r in packs) else 0.0

    # --- 90d replay comparison ---
    replay = load_replay_90d()
    print(f"replay_90d rows={len(replay)}", flush=True)
    X_rep = replay[FEATURE_COLS].astype(float).values
    regimes_rep = replay["regime"].astype(str).str.upper().values

    meta_ok = meta_gate(replay)
    pa_meta_accept = meta_ok.copy()

    single_accept = np.zeros(len(replay), dtype=bool)
    ens_accept = np.zeros(len(replay), dtype=bool)
    for i in range(len(replay)):
        reg = regimes_rep[i]
        if reg not in packs or not packs[reg]["fitted"]:
            continue
        if not meta_ok[i]:
            continue
        Xi = X_rep[i : i + 1]
        # single best model of that regime (or global best type if available)
        pack = packs[reg]
        mt = pack["best"]["model_type"] if pack.get("best") else list(pack["fitted"].keys())[0]
        # prefer global best_single if present in regime
        if best_single and best_single in pack["fitted"]:
            mt = best_single
        p_s = float(predict_single(pack, mt, Xi)[0])
        p_e = float(predict_ensemble(pack, Xi)[0])
        if p_s >= DECISION_THRESHOLD:
            single_accept[i] = True
        if p_e >= DECISION_THRESHOLD:
            ens_accept[i] = True

    paths = [
        eval_path("PA_META", replay, pa_meta_accept),
        eval_path("PA_META_SINGLE_BEST", replay, single_accept),
        eval_path("PA_META_REGIME_ENSEMBLE", replay, ens_accept),
    ]
    for p in paths:
        print(p, flush=True)

    ens_path = paths[2]
    replay_trades = int(ens_path["trades"])
    headline_pf = ens_tm["oos_pf"] if replay_trades < 10 else ens_path["pf"]
    headline_exp = ens_tm["oos_expectancy_r"] if replay_trades < 10 else ens_path["expectancy_r"]
    if headline_pf >= 900:
        headline_pf = ens_tm["oos_pf"]
    upgrade = bool(
        headline_pf >= 1.25
        and headline_exp >= 0.15
        and ens_brier < 0.12
        and ens_ece < 0.05
        and replay_trades >= 10
    )
    keep_shadow = True  # never enable live in this phase

    lines = [
        "PHASE 16C Regime-Aware ML Ensemble (Research Only)",
        "DATA=data/ml/research/phase13d/",
        "FEATURES=25 institutional store",
        "CV=PurgedKFold + embargo",
        "CALIBRATION=isotonic if OOF>=300 else platt",
        "ENSEMBLE_WEIGHT=max(PF-1,0)*(1-Brier)",
        "PATCH_APPLIED=NO USE_ML_KERNEL=unchanged",
        "",
        "=== Per-regime diagnostics ===",
    ]
    for regime in REGIMES:
        pack = packs[regime]
        lines.append(f"[{regime}] samples={pack['samples']}")
        for m in pack["models"]:
            met = m["metrics"]
            lines.append(
                f"  {m['model_type']}: OOS_PF={met['oos_pf']} OOS_Expectancy_R={met['oos_expectancy_r']} "
                f"Precision_BUY={met['precision_buy']} Precision_SELL={met['precision_sell']} "
                f"Recall={met['recall']} Brier={met['brier']} ECE={met['ece']} MCE={met['mce']} "
                f"PSI_vs_train={met['psi_vs_train']} weight={m['weight']:.4f} cal={met['calibration_method']}"
            )
        if pack.get("best"):
            lines.append(f"  BEST={pack['best']['model_type']}")

    lines.append("")
    lines.append("=== 90d PA replay comparison ===")
    lines.append(f"replay_rows={len(replay)}")
    for p in paths:
        lines.append(
            f"  {p['path']}: accepted_raw={p['accepted_raw']} trades={p['trades']} "
            f"PF={p['pf']} ExpR={p['expectancy_r']} WR={p['win_rate']}"
        )

    lines.append("")
    lines.append("=== Ensemble OOF aggregate ===")
    lines.append(f"ENSEMBLE_OOF_PF={ens_tm['oos_pf']}")
    lines.append(f"ENSEMBLE_OOF_EXPECTANCY_R={ens_tm['oos_expectancy_r']}")
    lines.append(f"ENSEMBLE_BRIER={round(ens_brier, 6)}")
    lines.append(f"ENSEMBLE_ECE={ens_ece}")
    lines.append(f"ENSEMBLE_MCE={ens_mce}")
    lines.append(f"ENSEMBLE_PSI={round(ens_psi, 6)}")

    lines.append("")
    lines.append("PHASE_16C_RESULT")
    lines.append(f"BEST_REGIME={best_regime}")
    lines.append(f"BEST_SINGLE_MODEL={best_regime}/{best_single}")
    lines.append(f"ENSEMBLE_PF={headline_pf}")
    lines.append(f"ENSEMBLE_EXPECTANCY_R={headline_exp}")
    lines.append(f"ENSEMBLE_REPLAY_TRADES={replay_trades}")
    lines.append(f"ENSEMBLE_BRIER={round(ens_brier, 6)}")
    lines.append(f"ENSEMBLE_ECE={ens_ece}")
    lines.append(f"ENSEMBLE_PSI={round(ens_psi, 6)}")
    lines.append(f"ML_SHADOW_UPGRADE_READY={'YES' if upgrade else 'NO'}")
    lines.append(f"KEEP_SHADOW_MODE={'YES' if keep_shadow else 'NO'}")

    text = "\n".join(lines) + "\n"
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text(text, encoding="utf-8")

    matrix["replay"] = {"rows": len(replay), "paths": paths}
    matrix["ensemble_oof"] = {
        "pf": ens_tm["oos_pf"],
        "expectancy_r": ens_tm["oos_expectancy_r"],
        "brier": ens_brier,
        "ece": ens_ece,
        "mce": ens_mce,
        "psi": ens_psi,
    }
    matrix["result"] = {
        "best_regime": best_regime,
        "best_single_model": f"{best_regime}/{best_single}",
        "ensemble_pf": headline_pf,
        "ensemble_expectancy_r": headline_exp,
        "ensemble_replay_trades": replay_trades,
        "ensemble_brier": ens_brier,
        "ensemble_ece": ens_ece,
        "ensemble_psi": ens_psi,
        "ml_shadow_upgrade_ready": upgrade,
        "keep_shadow_mode": keep_shadow,
    }
    # strip non-serializable fitted models
    serial_regimes = {}
    for regime, pack in packs.items():
        serial_regimes[regime] = {
            "samples": pack["samples"],
            "models": pack["models"],
            "best": pack["best"],
        }
    matrix["regimes"] = serial_regimes
    OUT_JSON.write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    print(text)
    print("WROTE", OUT_TXT)
    print("WROTE", OUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())