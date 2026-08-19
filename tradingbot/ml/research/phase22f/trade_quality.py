"""Phase 22F — executed trade quality metrics (MAE/MFE/RR)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import pip_size


def _holding_bars(entry, exit_, tf: str) -> int:
    minutes = {"M5": 5, "M15": 15, "H4": 240}.get(tf, 5)
    try:
        delta = exit_ - entry
        return max(1, int(delta.total_seconds() / 60 / minutes))
    except Exception:
        return 1


def analyze_trade_quality(
    trades_detail: list[dict],
    ohlcv: pd.DataFrame | None,
    *,
    timeframe: str = "M5",
) -> dict[str, Any]:
    if not trades_detail:
        return {"trades": 0, "records": []}

    records = []
    for t in trades_detail:
        entry_px = float(t.get("entry_price") or 0)
        exit_px = float(t.get("exit_price") or 0)
        sl = float(t.get("entry_sl") or 0)
        is_buy = t.get("side") == "BUY"
        r_mult = float(t.get("r_multiple") or 0)
        pnl = float(t.get("pnl") or 0)

        mae = mfe = 0.0
        rr_achieved = abs(r_mult)
        sl_eff = tp_eff = 0.0
        late_entry = early_exit = 0.0

        if ohlcv is not None and not ohlcv.empty and entry_px > 0 and sl > 0:
            entry_ts = pd.Timestamp(t.get("entry_time"))
            if entry_ts.tzinfo is None:
                entry_ts = entry_ts.tz_localize("UTC")
            idx = ohlcv.index.searchsorted(entry_ts)
            risk = abs(entry_px - sl)
            end = min(idx + 72, len(ohlcv) - 1)
            for j in range(idx + 1, end + 1):
                bar = ohlcv.iloc[j]
                hi, lo = float(bar["high"]), float(bar["low"])
                if is_buy:
                    mfe = max(mfe, (hi - entry_px) / risk if risk else 0)
                    mae = max(mae, (entry_px - lo) / risk if risk else 0)
                else:
                    mfe = max(mfe, (entry_px - lo) / risk if risk else 0)
                    mae = max(mae, (hi - entry_px) / risk if risk else 0)

        if t.get("reason") == "sl":
            sl_eff = 1.0
        elif t.get("reason") == "tp":
            tp_eff = 1.0

        if mfe > 0.5 and pnl < 0:
            early_exit = round(min(1.0, mfe - max(0, r_mult)), 3)
        if mae > 0.3 and pnl > 0:
            late_entry = round(min(1.0, mae * 0.5), 3)

        records.append({
            "side": t.get("side"),
            "entry_time": t.get("entry_time"),
            "pnl": pnl,
            "r_multiple": r_mult,
            "mae_r": round(mae, 4),
            "mfe_r": round(mfe, 4),
            "rr_achieved": round(rr_achieved, 4),
            "sl_efficiency": sl_eff,
            "tp_efficiency": tp_eff,
            "holding_bars": _holding_bars(
                pd.Timestamp(t.get("entry_time")),
                pd.Timestamp(t.get("exit_time")),
                timeframe,
            ),
            "late_entry_score": late_entry,
            "early_exit_score": early_exit,
            "exit_reason": t.get("reason"),
        })

    mae_avg = sum(r["mae_r"] for r in records) / len(records)
    mfe_avg = sum(r["mfe_r"] for r in records) / len(records)
    return {
        "timeframe": timeframe,
        "trades": len(records),
        "avg_mae_r": round(mae_avg, 4),
        "avg_mfe_r": round(mfe_avg, 4),
        "avg_rr_achieved": round(sum(r["rr_achieved"] for r in records) / len(records), 4),
        "avg_holding_bars": round(sum(r["holding_bars"] for r in records) / len(records), 2),
        "records": records,
    }
