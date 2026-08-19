"""Phase 45 — structure-event dataset builder (research only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

STRUCTURE_EVENT_TYPES = frozenset({
    "trading_session",
    "choch",
    "liquidity_sweep",
    "fvg",
    "bos",
    "order_block",
})


def filter_structure_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only non-session_transition structure events."""
    if "event_type" not in df.columns:
        return pd.DataFrame()
    work = df[df["event_type"].isin(STRUCTURE_EVENT_TYPES)].copy()
    return work.sort_values("timestamp").reset_index(drop=True)


def label_audit_by_event(df: pd.DataFrame, *, label_col: str = "label_v3") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for et, grp in df.groupby("event_type"):
        n = len(grp)
        wins = int(grp[label_col].sum())
        losses = n - wins
        pf = round(wins / losses, 4) if losses > 0 else (2.0 if wins > 0 else 0.0)
        rows.append({
            "event_type": str(et),
            "rows": n,
            "win_rate_pct": round(float(grp[label_col].mean()) * 100, 2),
            "label_pf_proxy": pf,
            "labels_changed_pct": round(float(grp["label_changed"].mean()) * 100, 2) if "label_changed" in grp else 0.0,
        })
    return sorted(rows, key=lambda x: -x["rows"])
