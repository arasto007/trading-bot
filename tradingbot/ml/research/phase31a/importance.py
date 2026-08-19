"""Permutation feature importance and interaction analysis."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.preprocessing import LabelEncoder

IMPORTANCE_FEATURES = [
    "confidence", "spread", "duration_bars",
    "counter_trend_score", "false_breakout_score", "htf_alignment_proxy",
    "wq_entry_quality", "wq_trend_quality", "wq_volatility_quality",
    "wq_momentum_quality", "wq_market_structure_quality", "wq_liquidity_quality",
    "wq_session_quality", "wq_probability_quality", "signal_filter_score",
    "risk_score", "min_lot_stress", "entry_hour",
]

# Post-trade outcomes excluded from importance to prevent leakage
LEAKY_FEATURES = {
    "pnl_r", "pnl", "mfe", "mae", "mfe_r", "mae_r", "capture_efficiency",
    "missed_opportunity_r", "mfe_capture_ratio", "mae_to_mfe",
}

CATEGORICAL = ["regime", "direction", "session", "exit_reason", "engine"]


def _prepare_Xy(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    cols = []
    X = pd.DataFrame(index=df.index)
    for c in IMPORTANCE_FEATURES:
        if c in df.columns:
            X[c] = pd.to_numeric(df[c], errors="coerce")
            cols.append(c)
    for c in CATEGORICAL:
        if c in df.columns:
            le = LabelEncoder()
            X[c] = le.fit_transform(df[c].astype(str).fillna("unknown"))
            cols.append(c)
    X = X.fillna(X.median(numeric_only=True))
    y = (df["pnl"] > 0).astype(int).values
    return X, y, cols


def compute_permutation_importance(df: pd.DataFrame) -> list[dict[str, Any]]:
    X, y, cols = _prepare_Xy(df)
    if len(X) < 20 or y.sum() < 5 or (1 - y).sum() < 5:
        return [{"feature": c, "importance": 0.0, "rank": i + 1} for i, c in enumerate(cols)]

    clf = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=6)
    clf.fit(X, y)
    perm = permutation_importance(clf, X, y, n_repeats=10, random_state=42, scoring="roc_auc")
    rows = []
    for i, c in enumerate(cols):
        rows.append(
            {
                "feature": c,
                "importance_mean": round(float(perm.importances_mean[i]), 5),
                "importance_std": round(float(perm.importances_std[i]), 5),
                "method": "permutation_importance",
                "target": "is_winner",
            }
        )
    rows.sort(key=lambda x: x["importance_mean"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def compute_interactions(df: pd.DataFrame, top_n: int = 30) -> list[dict[str, Any]]:
    dims = []
    for c in CATEGORICAL:
        if c in df.columns:
            dims.append((c, df[c].astype(str)))
    # Quantile bins for numeric
    for c in ["counter_trend_score", "false_breakout_score", "confidence", "wq_trend_quality"]:
        if c in df.columns:
            try:
                binned = pd.qcut(pd.to_numeric(df[c], errors="coerce").fillna(0), q=3, duplicates="drop")
                dims.append((c, binned.astype(str)))
            except Exception:
                pass

    interactions = []
    baseline_wr = float((df["pnl"] > 0).mean())
    baseline_pnl = float(df["pnl"].mean())

    for (n1, s1), (n2, s2) in combinations(dims, 2):
        tmp = df.copy()
        tmp["_a"] = s1.values
        tmp["_b"] = s2.values
        for (va, vb), sub in tmp.groupby(["_a", "_b"]):
            if len(sub) < 8:
                continue
            wr = float((sub["pnl"] > 0).mean())
            exp = float(sub["pnl"].mean())
            pf = _pf(sub)
            lift = wr - baseline_wr
            interactions.append(
                {
                    "dimension_a": n1,
                    "value_a": str(va),
                    "dimension_b": n2,
                    "value_b": str(vb),
                    "trade_count": int(len(sub)),
                    "win_rate": round(wr, 4),
                    "expectancy": round(exp, 4),
                    "pf": round(pf, 4),
                    "lift_vs_baseline": round(lift, 4),
                    "pnl_total": round(float(sub["pnl"].sum()), 2),
                }
            )

    interactions.sort(key=lambda x: abs(x["lift_vs_baseline"]) * x["trade_count"], reverse=True)
    return interactions[:top_n]


def _pf(sub: pd.DataFrame) -> float:
    wins = sub[sub["pnl"] > 0]["pnl"].sum()
    losses = abs(sub[sub["pnl"] <= 0]["pnl"].sum())
    return float(wins / losses) if losses > 0 else 999.0
