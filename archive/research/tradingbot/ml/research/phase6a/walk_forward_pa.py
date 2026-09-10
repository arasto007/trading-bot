"""Phase 6A — PA walk-forward (6×30d rolling windows)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

META_THRESHOLD = 0.38


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "pf": 0.0, "expectancy_r": 0.0, "win_rate_pct": 0.0}
    rs = [float(t["r_multiple"]) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    return {
        "trades": len(trades),
        "pf": round(pf, 3) if pf != 999.0 else "inf",
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "win_rate_pct": round(len(wins) / len(rs) * 100, 2),
    }


def _collect_pa_meta_trades(df: pd.DataFrame, *, meta_threshold: float = META_THRESHOLD) -> list[dict[str, Any]]:
    from logs.phase_c_meta_resurrection import apply_meta_filter, collect_pa_trades
    from tradingbot.services.meta_labeler import get_meta_labeler

    raw = collect_pa_trades(df)
    meta = get_meta_labeler()
    kept, _ = apply_meta_filter(raw, df, meta, threshold=meta_threshold, fp=None)
    return kept


def run_walk_forward(
    df: pd.DataFrame,
    *,
    n_windows: int = 6,
    window_days: int = 30,
    meta_threshold: float = META_THRESHOLD,
    all_trades: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Six rolling 30-day OOS windows on PA+Meta replay."""
    if df.empty:
        return {"windows": [], "median_pf": 0.0, "passes_gate": False}

    if all_trades is None:
        all_trades = _collect_pa_meta_trades(df, meta_threshold=meta_threshold)

    end = pd.Timestamp(df.index.max())
    if end.tzinfo is not None:
        end = end.tz_convert("UTC")
    windows: list[dict[str, Any]] = []

    for i in range(n_windows):
        w_end = end - timedelta(days=window_days * i)
        w_start = w_end - timedelta(days=window_days)
        window_trades = []
        for t in all_trades:
            ts = pd.Timestamp(t.get("bar_time", ""))
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            w_start_cmp = w_start.tz_localize("UTC") if w_start.tzinfo is None else w_start
            w_end_cmp = w_end.tz_localize("UTC") if w_end.tzinfo is None else w_end
            if w_start_cmp < ts <= w_end_cmp:
                window_trades.append(t)
        m = _metrics(window_trades)
        windows.append({
            "window": i + 1,
            "start": str(w_start.date()),
            "end": str(w_end.date()),
            "bars": int(((df.index > w_start) & (df.index <= w_end)).sum()),
            "skipped": len(window_trades) == 0 and m["trades"] == 0,
            **m,
        })

    pfs = [float(w["pf"]) for w in windows if w.get("trades", 0) > 0 and w["pf"] != "inf"]
    median_pf = float(pd.Series(pfs).median()) if pfs else 0.0
    return {
        "windows": windows,
        "median_pf": round(median_pf, 3),
        "passes_gate": median_pf > 1.3,
        "n_windows": n_windows,
        "window_days": window_days,
    }
