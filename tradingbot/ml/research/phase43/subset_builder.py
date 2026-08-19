"""Phase 43 — balanced event subsets for retrain (research only)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_subsets(df: pd.DataFrame, *, seed: int = 42) -> dict[str, pd.DataFrame]:
    """Create chronologically-safe research subsets to reduce session_transition dominance."""
    work = df[df["label_v3"].isin([0, 1])].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp").reset_index(drop=True)

    signal = work[work["event_type"] != "session_transition"].copy()
    session = work[work["event_type"] == "session_transition"].copy()

    # Keep all signal-like events; downsample session_transition to match signal count.
    target = max(len(signal), 400)
    if len(session) > target:
        session = session.sample(n=target, random_state=seed).sort_values("timestamp")
    balanced = pd.concat([signal, session], ignore_index=True).sort_values("timestamp")

    # Trading-session + structure events only (highest signal quality hypothesis).
    structure_types = {"trading_session", "choch", "liquidity_sweep", "fvg"}
    structure = work[work["event_type"].isin(structure_types)].copy()

    return {
        "v3_full": work,
        "v4_balanced": balanced,
        "v4_signal_only": signal,
        "v4_structure": structure,
    }


def subset_summary(subsets: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, df in subsets.items():
        if df.empty:
            rows.append({"subset": name, "rows": 0})
            continue
        dom = df["event_type"].value_counts().index[0]
        dom_share = round(float(df["event_type"].value_counts().iloc[0] / len(df) * 100), 2)
        rows.append({
            "subset": name,
            "rows": len(df),
            "win_rate_pct": round(float(df["label_v3"].mean()) * 100, 2),
            "dominant_event": dom,
            "dominant_share_pct": dom_share,
        })
    return rows
