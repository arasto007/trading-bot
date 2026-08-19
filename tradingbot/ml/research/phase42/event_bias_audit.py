"""Phase 42 — event sampling bias audit (research only)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def event_bias_report(df: pd.DataFrame, *, label_col: str = "label_v3") -> dict[str, Any]:
    if df.empty or "event_type" not in df.columns:
        return {"verdict": "INSUFFICIENT_DATA"}

    work = df[df[label_col].isin([0, 1])].copy()
    total = len(work)
    by_event: list[dict[str, Any]] = []
    for et, grp in work.groupby("event_type"):
        by_event.append({
            "event_type": str(et),
            "rows": len(grp),
            "share_pct": round(len(grp) / max(total, 1) * 100, 2),
            "win_rate_pct": round(float(grp[label_col].mean()) * 100, 2),
            "labels_changed_pct": round(float(grp["label_changed"].mean()) * 100, 2) if "label_changed" in grp else 0.0,
        })
    by_event.sort(key=lambda x: -x["rows"])

    dominant = by_event[0] if by_event else {}
    dom_share = float(dominant.get("share_pct", 0))
    signal_rows = int(work.loc[work["event_type"] != "session_transition"].shape[0])
    signal_share = round(signal_rows / max(total, 1) * 100, 2)

    if dom_share >= 80:
        verdict = "SEVERE_EVENT_BIAS"
    elif dom_share >= 60:
        verdict = "MODERATE_EVENT_BIAS"
    else:
        verdict = "ACCEPTABLE_EVENT_MIX"

    return {
        "verdict": verdict,
        "total_rows": total,
        "dominant_event": dominant.get("event_type"),
        "dominant_share_pct": dom_share,
        "signal_event_rows": signal_rows,
        "signal_event_share_pct": signal_share,
        "by_event_type": by_event,
        "recommendation": "DOWNSAMPLE_SESSION_TRANSITION_AND_RETRAIN",
    }
