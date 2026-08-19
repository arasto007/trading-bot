"""Automatic trade clustering — discovered, not hardcoded."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

FEATURE_POOL = [
    "confidence", "pnl_r", "mfe", "mae", "duration_bars", "spread", "rr",
    "capture_efficiency", "missed_opportunity_r", "mfe_r", "mae_r",
    "counter_trend_score", "false_breakout_score", "htf_alignment_proxy",
    "wq_entry_quality", "wq_trend_quality", "wq_volatility_quality",
    "wq_momentum_quality", "wq_market_structure_quality", "signal_filter_score",
    "risk_score", "min_lot_stress", "mfe_capture_ratio", "mae_to_mfe",
]

LABEL_FEATURES = [
    ("pnl_r", "pnl"),
    ("mfe_r", "mfe"),
    ("mae_r", "mae"),
    ("capture_efficiency", "capture"),
    ("counter_trend_score", "counter_trend"),
    ("false_breakout_score", "weak_breakout"),
    ("wq_trend_quality", "trend_q"),
    ("confidence", "confidence"),
    ("duration_bars", "hold"),
    ("missed_opportunity_r", "missed_r"),
]


def _numeric_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    cols = [c for c in FEATURE_POOL if c in df.columns]
    mat = df[cols].copy()
    for c in cols:
        mat[c] = pd.to_numeric(mat[c], errors="coerce")
    med = mat.median(numeric_only=True)
    for c in cols:
        fill = med[c] if c in med and pd.notna(med[c]) else 0.0
        mat[c] = mat[c].fillna(fill)
    mat = mat.replace([np.inf, -np.inf], 0.0)
    return mat, cols


def _auto_k(X: np.ndarray, k_min: int = 4, k_max: int = 12) -> int:
    best_k, best_score = k_min, -1.0
    for k in range(k_min, min(k_max + 1, len(X))):
        if k >= len(X):
            break
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(X, labels)
        if score > best_score:
            best_score = score
            best_k = k
    return best_k


def _name_cluster(centroid: pd.Series, global_mean: pd.Series, global_std: pd.Series) -> str:
    tags: list[str] = []
    for feat, short in LABEL_FEATURES:
        if feat not in centroid.index:
            continue
        z = (centroid[feat] - global_mean[feat]) / (global_std[feat] + 1e-9)
        if z >= 0.6:
            tags.append(f"high_{short}")
        elif z <= -0.6:
            tags.append(f"low_{short}")
    if not tags:
        tags = ["mixed_profile"]
    outcome = "winners" if centroid.get("pnl_r", 0) > 0.05 else "losers" if centroid.get("pnl_r", 0) < -0.05 else "mediocre"
    return "_".join(tags[:3]) + f"_{outcome}"


def discover_clusters(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    mat, cols = _numeric_matrix(df)
    scaler = StandardScaler()
    X = scaler.fit_transform(mat.values)
    k = _auto_k(X)
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    out = df.copy()
    out["cluster_id"] = labels

    centroids = pd.DataFrame(scaler.inverse_transform(km.cluster_centers_), columns=cols)
    g_mean = mat.mean()
    g_std = mat.std()

    cluster_meta = []
    for cid in range(k):
        sub = out[out["cluster_id"] == cid]
        centroid = centroids.iloc[cid]
        name = _name_cluster(centroid, g_mean, g_std)
        wins = sub[sub["pnl"] > 0]
        losses = sub[sub["pnl"] <= 0]
        gross_win = wins["pnl"].sum() if len(wins) else 0.0
        gross_loss = abs(losses["pnl"].sum()) if len(losses) else 0.0
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        cluster_meta.append(
            {
                "cluster_id": int(cid),
                "discovered_name": name,
                "trade_count": int(len(sub)),
                "winners": int(len(wins)),
                "losers": int(len(losses)),
                "pf": round(pf, 4) if pf != float("inf") else 999.0,
                "expectancy": round(float(sub["pnl"].mean()), 4),
                "total_pnl": round(float(sub["pnl"].sum()), 4),
                "avg_mae": round(float(sub["mae"].mean()), 4),
                "avg_mfe": round(float(sub["mfe"].mean()), 4),
                "avg_duration_bars": round(float(sub["duration_bars"].mean()), 2),
                "avg_confidence": round(float(sub["confidence"].mean()), 4),
                "confidence_cluster": round(min(95, 50 + len(sub) / max(len(df), 1) * 100), 1),
                "importance": round(abs(float(sub["pnl"].sum())) / max(abs(df["pnl"].sum()), 1) * 100, 2),
                "statistical_significance": _significance(len(sub), len(df)),
                "centroid_top_features": _top_z_features(centroid, g_mean, g_std),
            }
        )

    cluster_meta.sort(key=lambda x: x["total_pnl"])
    return out, cluster_meta, k


def _top_z_features(centroid: pd.Series, mean: pd.Series, std: pd.Series, n: int = 5) -> list[dict]:
    zs = []
    for feat in centroid.index:
        z = (centroid[feat] - mean[feat]) / (std[feat] + 1e-9)
        zs.append({"feature": feat, "z_score": round(float(z), 3)})
    zs.sort(key=lambda x: abs(x["z_score"]), reverse=True)
    return zs[:n]


def _significance(n_cluster: int, n_total: int) -> str:
    pct = n_cluster / max(n_total, 1) * 100
    if n_cluster >= 30 and pct >= 5:
        return "HIGH"
    if n_cluster >= 15:
        return "MEDIUM"
    return "LOW"


def split_by_outcome(cluster_meta: list[dict]) -> tuple[list, list, list]:
    winners = [c for c in cluster_meta if c["expectancy"] > 0.1]
    losers = [c for c in cluster_meta if c["expectancy"] < -0.1]
    mediocre = [c for c in cluster_meta if c not in winners and c not in losers]
    return winners, losers, mediocre
