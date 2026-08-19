"""PHASE 15B — MFE / MAE Intelligence (research only).

For each labeled setup: setup_score, MFE_R, MAE_R, final_R.
Correlate setup characteristics with high MFE, low MAE, high final R.
No live / config / execution changes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

FEATURE_COLS = [
    "setup_score",
    "sweep_quality",
    "displacement_strength",
    "fvg_quality",
    "order_block_quality",
    "htf_bias_alignment",
    "premium_discount",
    "htf_bias",
    "direction",
    "planned_rr",
    "risk_atr",
    "sweep_x_disp",
    "fvg_x_ob",
    "htf_x_pd",
    "score_x_rr",
]


def path_mfe_mae_final(
    df: pd.DataFrame,
    i: int,
    *,
    direction: int,
    entry: float,
    sl: float,
    tp: float,
    max_bars: int = 96,
) -> tuple[float, float, float]:
    """Compute MFE_R, MAE_R along path until SL/TP/timeout; final_R at exit."""
    risk = abs(entry - sl)
    if risk <= 0 or i >= len(df) - 1:
        return 0.0, 0.0, 0.0
    end = min(len(df), i + 1 + max_bars)
    mfe = mae = 0.0
    final_r = 0.0
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        if direction > 0:
            mfe = max(mfe, max(0.0, (hi - entry) / risk))
            mae = max(mae, max(0.0, (entry - lo) / risk))
            if lo <= sl:
                final_r = (sl - entry) / risk
                return round(mfe, 4), round(mae, 4), round(final_r, 4)
            if hi >= tp:
                final_r = (tp - entry) / risk
                return round(mfe, 4), round(mae, 4), round(final_r, 4)
        else:
            mfe = max(mfe, max(0.0, (entry - lo) / risk))
            mae = max(mae, max(0.0, (hi - entry) / risk))
            if hi >= sl:
                final_r = (entry - sl) / risk
                return round(mfe, 4), round(mae, 4), round(final_r, 4)
            if lo <= tp:
                final_r = (entry - tp) / risk
                return round(mfe, 4), round(mae, 4), round(final_r, 4)
    close = float(df["close"].iloc[end - 1])
    final_r = ((close - entry) if direction > 0 else (entry - close)) / risk
    return round(mfe, 4), round(mae, 4), round(final_r, 4)


def load_m5() -> pd.DataFrame:
    path = ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet"
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    if "atr" not in df.columns:
        df = df.copy()
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()
    return df


def enrich_features(labeled: pd.DataFrame, m5: pd.DataFrame) -> pd.DataFrame:
    out = labeled.copy()
    atrs = []
    mfe_l, mae_l, final_l = [], [], []
    for _, row in out.iterrows():
        i = int(row["bar_index"])
        entry = float(row["entry"])
        sl = float(row["stop_loss"])
        tp = float(row["take_profit"])
        direction = int(row["direction"])
        atr = float(m5["atr"].iloc[i]) if i < len(m5) and not pd.isna(m5["atr"].iloc[i]) else abs(entry - sl)
        atr = max(atr, 1e-9)
        atrs.append(abs(entry - sl) / atr)
        mfe, mae, final_r = path_mfe_mae_final(
            m5, i, direction=direction, entry=entry, sl=sl, tp=tp
        )
        mfe_l.append(mfe)
        mae_l.append(mae)
        final_l.append(final_r)

    out["risk_atr"] = atrs
    out["planned_rr"] = (out["take_profit"] - out["entry"]).abs() / (out["entry"] - out["stop_loss"]).abs().clip(lower=1e-9)
    out["MFE_R"] = mfe_l
    out["MAE_R"] = mae_l
    out["final_R"] = final_l
    # interaction features
    out["sweep_x_disp"] = out["sweep_quality"] * out["displacement_strength"] / 100.0
    out["fvg_x_ob"] = out["fvg_quality"] * out["order_block_quality"] / 100.0
    out["htf_x_pd"] = out["htf_bias_alignment"] * out["premium_discount"] / 100.0
    out["score_x_rr"] = out["setup_score"] * out["planned_rr"] / 100.0
    # low-MAE target helper (higher is better)
    out["neg_MAE_R"] = -out["MAE_R"]
    return out


def corr_table(df: pd.DataFrame, features: list[str], target: str, method: str = "spearman") -> pd.DataFrame:
    rows = []
    y = df[target]
    for f in features:
        x = df[f]
        if x.nunique(dropna=True) < 2:
            r = 0.0
        else:
            r = float(x.corr(y, method=method))
            if np.isnan(r):
                r = 0.0
        rows.append({"feature": f, "corr": round(r, 4), "abs_corr": round(abs(r), 4), "target": target})
    return pd.DataFrame(rows).sort_values("abs_corr", ascending=False).reset_index(drop=True)


def importance_rank(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Rank by mean abs Spearman corr across MFE, low-MAE, final_R."""
    c_mfe = corr_table(df, features, "MFE_R").set_index("feature")["corr"]
    c_mae = corr_table(df, features, "neg_MAE_R").set_index("feature")["corr"]
    c_fin = corr_table(df, features, "final_R").set_index("feature")["corr"]
    rows = []
    for f in features:
        a = abs(float(c_mfe.get(f, 0.0)))
        b = abs(float(c_mae.get(f, 0.0)))
        c = abs(float(c_fin.get(f, 0.0)))
        score = (a + b + c) / 3.0
        rows.append(
            {
                "feature": f,
                "corr_mfe": round(float(c_mfe.get(f, 0.0)), 4),
                "corr_low_mae": round(float(c_mae.get(f, 0.0)), 4),
                "corr_final_r": round(float(c_fin.get(f, 0.0)), 4),
                "importance": round(score, 4),
            }
        )
    return pd.DataFrame(rows).sort_values("importance", ascending=False).reset_index(drop=True)


def run_phase15b() -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    csv_path = ROOT / "logs" / "phase15a_setup_scores.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing {csv_path}; run Phase 15A first.")

    labeled = pd.read_csv(csv_path)
    print(f"labeled={len(labeled)} loading M5...", flush=True)
    m5 = load_m5()
    df = enrich_features(labeled, m5)

    # Prefer traded subset for outcome intelligence; fall back to all if tiny
    work = df[df["traded"] == 1].copy() if "traded" in df.columns else df.copy()
    if len(work) < 30:
        work = df.copy()
        sample_note = "ALL_SETUPS"
    else:
        sample_note = "TRADED_ONLY"

    print(f"sample={sample_note} n={len(work)}", flush=True)

    features = [f for f in FEATURE_COLS if f in work.columns]
    rank = importance_rank(work, features)
    mfe_rank = corr_table(work, features, "MFE_R")
    mae_rank = corr_table(work, features, "neg_MAE_R")
    fin_rank = corr_table(work, features, "final_R")

    best_mfe = str(mfe_rank.iloc[0]["feature"])
    best_mae = str(mae_rank.iloc[0]["feature"])
    best_fin = str(fin_rank.iloc[0]["feature"])
    best_mfe_r = float(mfe_rank.iloc[0]["corr"])
    best_mae_r = float(mae_rank.iloc[0]["corr"])
    best_fin_r = float(fin_rank.iloc[0]["corr"])

    # Edge if any meaningful predictive association with final_R or dual MFE/MAE
    edge = bool(
        abs(best_fin_r) >= 0.20
        or (abs(best_mfe_r) >= 0.15 and abs(best_mae_r) >= 0.15)
        or float(rank.iloc[0]["importance"]) >= 0.18
    )

    # Export enriched CSV for audit
    out_csv = ROOT / "logs" / "phase15b_mfe_mae_labeled.csv"
    export_cols = [
        c
        for c in [
            "timestamp",
            "bar_index",
            "direction",
            "setup_score",
            "sweep_quality",
            "displacement_strength",
            "fvg_quality",
            "order_block_quality",
            "htf_bias_alignment",
            "premium_discount",
            "planned_rr",
            "risk_atr",
            "MFE_R",
            "MAE_R",
            "final_R",
            "traded",
        ]
        if c in df.columns
    ]
    df[export_cols].to_csv(out_csv, index=False)

    lines: list[str] = [
        "PHASE 15B MFE / MAE Intelligence (Research Only)",
        "DATA=XAUUSD_M5_90d + phase15a_setup_scores.csv",
        "PATCH_APPLIED=NO",
        f"SAMPLE={sample_note}",
        f"N={len(work)}",
        f"ALL_LABELED={len(df)}",
        "",
        f"MEAN_MFE_R={round(float(work['MFE_R'].mean()), 4)}",
        f"MEAN_MAE_R={round(float(work['MAE_R'].mean()), 4)}",
        f"MEAN_FINAL_R={round(float(work['final_R'].mean()), 4)}",
        f"MEDIAN_MFE_R={round(float(work['MFE_R'].median()), 4)}",
        f"MEDIAN_MAE_R={round(float(work['MAE_R'].median()), 4)}",
        "",
        "=== Correlations with HIGH MFE (Spearman) ===",
    ]
    for i, row in mfe_rank.head(10).iterrows():
        lines.append(f"  {i+1:02d}. {row['feature']:24s} corr={row['corr']:+.4f}")

    lines.append("")
    lines.append("=== Correlations with LOW MAE (Spearman vs -MAE_R) ===")
    for i, row in mae_rank.head(10).iterrows():
        lines.append(f"  {i+1:02d}. {row['feature']:24s} corr={row['corr']:+.4f}")

    lines.append("")
    lines.append("=== Correlations with HIGH final_R (Spearman) ===")
    for i, row in fin_rank.head(10).iterrows():
        lines.append(f"  {i+1:02d}. {row['feature']:24s} corr={row['corr']:+.4f}")

    lines.append("")
    lines.append("=== Top 20 Predictive Features (importance = mean |corr| over MFE, low-MAE, final_R) ===")
    top20 = rank.head(20)
    for i, row in top20.iterrows():
        lines.append(
            f"  {i+1:02d}. {row['feature']:24s} importance={row['importance']:.4f} "
            f"(mfe={row['corr_mfe']:+.3f}, low_mae={row['corr_low_mae']:+.3f}, final_R={row['corr_final_r']:+.3f})"
        )

    lines.append("")
    lines.append("=== Full Characteristic Ranking ===")
    for i, row in rank.iterrows():
        lines.append(f"  {i+1:02d}. {row['feature']:24s} importance={row['importance']:.4f}")

    lines.append("")
    lines.append("PHASE_15B_RESULT")
    lines.append(f"BEST_MFE_FEATURE={best_mfe}")
    lines.append(f"BEST_MAE_FEATURE={best_mae}")
    lines.append(f"BEST_FINAL_R_FEATURE={best_fin}")
    lines.append(f"EDGE_DISCOVERED={'YES' if edge else 'NO'}")
    lines.append(f"BEST_MFE_CORR={best_mfe_r}")
    lines.append(f"BEST_MAE_CORR={best_mae_r}")
    lines.append(f"BEST_FINAL_R_CORR={best_fin_r}")

    text = "\n".join(lines) + "\n"
    out_txt = ROOT / "logs" / "phase15b_mfe_mae_report.txt"
    out_txt.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase15b_mfe_mae_report.json").write_text(
        json.dumps(
            {
                "sample": sample_note,
                "n": len(work),
                "best_mfe_feature": best_mfe,
                "best_mae_feature": best_mae,
                "best_final_r_feature": best_fin,
                "edge_discovered": edge,
                "top20": top20.to_dict(orient="records"),
                "ranking": rank.to_dict(orient="records"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(text)
    print("WROTE", out_txt)
    print("WROTE", out_csv)
    return {
        "best_mfe_feature": best_mfe,
        "best_mae_feature": best_mae,
        "best_final_r_feature": best_fin,
        "edge_discovered": edge,
    }


if __name__ == "__main__":
    raise SystemExit(0 if run_phase15b() else 1)