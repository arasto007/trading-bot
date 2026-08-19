"""Load and merge completed trade datasets for Phase 31A."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[4]

PATHS = {
    "wpsqf_replay": PROJECT_ROOT / "tradingbot/ml/research/phase29b/_cache/wpsqf/replay_meta.json",
    "off_replay": PROJECT_ROOT / "tradingbot/ml/research/phase29b/_cache/off/replay_meta.json",
    "quality_scores": PROJECT_ROOT / "tradingbot/ml/research/phase29a/trade_quality_scores.json",
    "edge_per_trade": PROJECT_ROOT / "tradingbot/ml/research/phase27j/edge_per_trade.json",
    "losing_log": PROJECT_ROOT / "tradingbot/ml/research/phase27k/losing_trade_log.json",
    "replay_records": PROJECT_ROOT / "tradingbot/ml/research/phase29b/_cache/wpsqf/replay_records.json",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_wpsqf_trades() -> tuple[pd.DataFrame, dict[str, Any]]:
    doc = _load_json(PATHS["wpsqf_replay"])
    trades = doc["accounting"]["trades"]
    meta = {
        "trade_count": len(trades),
        "ledger": doc["accounting"]["ledger"],
        "portfolio": doc.get("replay_portfolio", {}),
    }
    return pd.DataFrame(trades), meta


def load_quality_scores() -> pd.DataFrame:
    doc = _load_json(PATHS["quality_scores"])
    rows = []
    for t in doc["trades"]:
        row = {
            "trade_id": t["trade_id"],
            "timestamp": t["timestamp"],
            "quality_score": t.get("quality_score"),
            "signal_filter_score": t.get("signal_filter_score"),
            "wpsqf_quality_score": t.get("quality_score"),
        }
        comps = t.get("components") or {}
        for k, v in comps.items():
            row[f"wq_{k}"] = v
        rows.append(row)
    return pd.DataFrame(rows)


def load_edge_per_trade() -> pd.DataFrame:
    doc = _load_json(PATHS["edge_per_trade"])
    return pd.DataFrame(doc["trades"])


def load_losing_enrichment() -> pd.DataFrame:
    doc = _load_json(PATHS["losing_log"])
    rows = []
    for t in doc["trades"]:
        pre = t.get("pre_entry") or {}
        fb = t.get("first_bars") or {}
        rows.append(
            {
                "entry_timestamp": t["entry_timestamp"],
                "loser_adx": t.get("adx"),
                "loser_rsi": t.get("rsi"),
                "loser_atr": t.get("atr"),
                "loser_mae_r": t.get("mae_r"),
                "loser_mfe_r": t.get("mfe_r"),
                "false_signal_class": t.get("false_signal_class"),
                "ever_profitable": t.get("ever_profitable"),
                "pre_ema_alignment": pre.get("ema_alignment"),
                "pre_market_structure": pre.get("market_structure"),
                "pre_atr_percentile": pre.get("atr_percentile"),
                "bar_1_in_profit": fb.get("bar_1_in_profit"),
                "bar_10_in_profit": fb.get("bar_10_in_profit"),
            }
        )
    return pd.DataFrame(rows)


def load_bar_records() -> pd.DataFrame:
    doc = _load_json(PATHS["replay_records"])
    records = doc if isinstance(doc, list) else doc.get("records", [])
    return pd.DataFrame(records)


def build_master_frame() -> tuple[pd.DataFrame, dict[str, Any]]:
    trades, meta = load_wpsqf_trades()
    quality = load_quality_scores()
    edge = load_edge_per_trade()
    losers = load_losing_enrichment()

    df = trades.copy()
    df["is_winner"] = df["pnl"] > 0
    df["is_loser"] = df["pnl"] <= 0
    df["outcome"] = df["is_winner"].map({True: "winner", False: "loser"})
    df["mediocre"] = (df["pnl_r"].abs() < 0.15) & (df["duration_bars"] <= 2)

    df = df.merge(quality, on=["trade_id", "timestamp"], how="left", suffixes=("", "_q"))

    edge_cols = [
        "timestamp", "gross_edge", "net_edge", "capture_efficiency", "missed_opportunity_r",
        "mfe_r", "mae_r", "post_exit_opportunity_r", "exit_timing_loss_dollars", "atr_at_entry",
    ]
    edge_sub = edge[[c for c in edge_cols if c in edge.columns]].copy()
    df = df.merge(edge_sub, on="timestamp", how="left")

    df = df.merge(losers, left_on="timestamp", right_on="entry_timestamp", how="left")

    # Derived forensic dimensions
    df["mfe_capture_ratio"] = df.apply(
        lambda r: (r["pnl_r"] / r["mfe"]) if r.get("mfe") and r["mfe"] > 0 else 0.0, axis=1
    )
    df["mae_to_mfe"] = df.apply(
        lambda r: (r["mae"] / r["mfe"]) if r.get("mfe") and r["mfe"] > 0 else 0.0, axis=1
    )
    df["counter_trend_score"] = 100 - df.get("wq_trend_quality", pd.Series(50, index=df.index)).fillna(50)
    df["false_breakout_score"] = 100 - df.get("wq_market_structure_quality", pd.Series(50, index=df.index)).fillna(50)
    df["entry_hour"] = pd.to_datetime(df["timestamp"], utc=True).dt.hour
    df["session"] = df["entry_hour"].apply(_session_from_hour)
    df["htf_alignment_proxy"] = df.get("wq_trend_quality", pd.Series(50, index=df.index)).fillna(50)
    df["risk_score"] = df.get("actual_risk_percent", df.get("risk_percent", 0)).fillna(0)
    df["min_lot_stress"] = df.get("min_lot_limit_applied", False).astype(int)

    meta["merged_columns"] = len(df.columns)
    meta["winners"] = int(df["is_winner"].sum())
    meta["losers"] = int(df["is_loser"].sum())
    meta["mediocre_count"] = int(df["mediocre"].sum())
    return df, meta


def _session_from_hour(hour: int) -> str:
    if 0 <= hour < 8:
        return "Asian"
    if 8 <= hour < 13:
        return "London"
    if 13 <= hour < 16:
        return "Overlap"
    if 16 <= hour < 21:
        return "NewYork"
    return "Asian"
