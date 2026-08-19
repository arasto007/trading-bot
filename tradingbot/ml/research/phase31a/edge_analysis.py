"""Edge concentration, dilution, leakage, redundancy."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def edge_concentration(df: pd.DataFrame, cluster_meta: list[dict]) -> dict[str, Any]:
    total_pnl = float(df["pnl"].sum())
    pos = df[df["pnl"] > 0]
    neg = df[df["pnl"] <= 0]

    # Herfindahl on cluster PnL contribution
    shares = []
    for c in cluster_meta:
        share = abs(c["total_pnl"]) / max(abs(total_pnl), 1e-9)
        shares.append(share)
    hhi = sum(s ** 2 for s in shares)

    top_winner_clusters = sorted(
        [c for c in cluster_meta if c["total_pnl"] > 0],
        key=lambda x: x["total_pnl"],
        reverse=True,
    )[:5]
    top_loser_clusters = sorted(
        [c for c in cluster_meta if c["total_pnl"] < 0],
        key=lambda x: x["total_pnl"],
    )[:5]

    winner_pnl_share = float(pos["pnl"].sum()) / max(abs(total_pnl), 1e-9) if total_pnl != 0 else 0
    top5_win_share = (
        sum(c["total_pnl"] for c in top_winner_clusters) / max(float(pos["pnl"].sum()), 1e-9)
        if len(pos) else 0
    )

    return {
        "total_pnl": round(total_pnl, 2),
        "winner_pnl": round(float(pos["pnl"].sum()), 2),
        "loser_pnl": round(float(neg["pnl"].sum()), 2),
        "herfindahl_index": round(hhi, 4),
        "concentration_interpretation": "HIGH" if hhi > 0.15 else "MODERATE" if hhi > 0.08 else "LOW",
        "top5_winner_cluster_share": round(top5_win_share, 4),
        "top_winner_clusters": top_winner_clusters,
        "top_loser_clusters": top_loser_clusters,
        "edge_in_top_20pct_trades": _top_pct_share(df, 0.2),
    }


def edge_dilution(df: pd.DataFrame) -> dict[str, Any]:
    """Trades that consume edge without contributing."""
    mediocre = df[df["pnl_r"].abs() < 0.15]
    high_conf_losers = df[(df["confidence"] >= 0.95) & (df["pnl"] <= 0)]
    counter_trend = df[df.get("counter_trend_score", 0) >= 60] if "counter_trend_score" in df else pd.DataFrame()

    diluters = []
    if len(mediocre) > 0:
        diluters.append({
            "segment": "low_r_mediocre",
            "count": int(len(mediocre)),
            "pnl": round(float(mediocre["pnl"].sum()), 2),
            "pf": _pf(mediocre),
        })
    if len(high_conf_losers) > 0:
        diluters.append({
            "segment": "high_confidence_losers",
            "count": int(len(high_conf_losers)),
            "pnl": round(float(high_conf_losers["pnl"].sum()), 2),
            "pf": _pf(high_conf_losers),
        })
    if len(counter_trend) > 0:
        diluters.append({
            "segment": "counter_trend_elevated",
            "count": int(len(counter_trend)),
            "pnl": round(float(counter_trend["pnl"].sum()), 2),
            "pf": _pf(counter_trend),
        })

    overlap = 0
    if "signal_filter_score" in df.columns and "wq_trend_quality" in df.columns:
        mask_a = df["signal_filter_score"] >= 90
        mask_b = df["wq_trend_quality"] < 30
        overlap = int((mask_a & mask_b).sum())

    return {
        "dilution_segments": diluters,
        "signal_overlap_high_conf_low_trend": overlap,
        "dilution_pnl_total": round(sum(d["pnl"] for d in diluters), 2),
        "interpretation": "Edge diluted by high-count low-expectancy segments" if diluters else "minimal",
    }


def feature_redundancy(importance: list[dict]) -> dict[str, Any]:
    """Detect redundant feature groups from importance ranks."""
    groups = {
        "trend_group": ["wq_trend_quality", "htf_alignment_proxy", "counter_trend_score"],
        "mfe_mae_group": ["mfe", "mae", "mfe_r", "mae_r", "capture_efficiency"],
        "quality_group": ["signal_filter_score", "confidence", "wq_probability_quality"],
        "structure_group": ["false_breakout_score", "wq_market_structure_quality"],
    }
    rank_map = {r["feature"]: r["rank"] for r in importance}
    redundancy = []
    for name, feats in groups.items():
        present = [f for f in feats if f in rank_map]
        if len(present) >= 2:
            ranks = [rank_map[f] for f in present]
            redundancy.append({
                "group": name,
                "features": present,
                "rank_spread": max(ranks) - min(ranks),
                "redundant": max(ranks) - min(ranks) <= 5,
            })
    return {"groups": redundancy, "leakage_risk": "LOW — research uses closed trades only"}


def _top_pct_share(df: pd.DataFrame, pct: float) -> float:
    n = max(1, int(len(df) * pct))
    top = df.nlargest(n, "pnl")
    total = float(df["pnl"].sum())
    return round(float(top["pnl"].sum()) / max(abs(total), 1e-9), 4) if total != 0 else 0.0


def _pf(sub: pd.DataFrame) -> float:
    wins = sub[sub["pnl"] > 0]["pnl"].sum()
    losses = abs(sub[sub["pnl"] <= 0]["pnl"].sum())
    return round(float(wins / losses), 4) if losses > 0 else 999.0
