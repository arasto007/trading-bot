"""Build completed trades from unified pipeline replay records."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase26a.exit_simulator import simulate_trade_exit


def build_completed_trades(
    records: list[dict[str, Any]],
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
) -> list[dict[str, Any]]:
    """Convert executed replay signals into completed trade lifecycle dicts."""
    if candles is None or candles.empty:
        return []

    frame = candles.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "time" in frame.columns:
            frame = frame.set_index("time")
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))

    trades: list[dict[str, Any]] = []
    seen: set[str] = set()

    for rec in records:
        direction = str(rec.get("decision", "HOLD"))
        if direction not in ("BUY", "SELL"):
            continue
        if not rec.get("execution_success"):
            continue

        ts = str(rec.get("timestamp") or "")
        if not ts or ts in seen:
            continue
        seen.add(ts)

        sl = rec.get("sl")
        tp = rec.get("tp")
        sl_f = float(sl) if sl is not None else None
        tp_f = float(tp) if tp is not None else None
        lot = float(rec.get("volume") or 0.01)

        entry_idx = frame.index.searchsorted(pd.to_datetime(ts, utc=True))
        entry_idx = min(max(int(entry_idx), 0), len(frame) - 1)
        entry_price = float(frame.iloc[entry_idx]["close"])
        if entry_price <= 0:
            continue

        exit_info = simulate_trade_exit(
            candles=frame,
            entry_ts=ts,
            entry_price=entry_price,
            sl=sl_f,
            tp=tp_f,
            is_buy=direction == "BUY",
            lot=lot,
            symbol=symbol,
        )
        if exit_info.get("exit_reason") == "no_data":
            continue

        risk_unit = abs(entry_price - sl_f) if sl_f is not None else None
        rr = exit_info.get("rr")

        trades.append(
            {
                "timestamp": ts,
                "exit_timestamp": exit_info["exit_timestamp"],
                "symbol": symbol,
                "timeframe": rec.get("timeframe", "M5"),
                "direction": direction,
                "regime": str(rec.get("regime") or "UNKNOWN"),
                "engine": str(rec.get("engine") or ""),
                "confidence": float(rec.get("confidence") or 0.0),
                "probability": float(rec.get("confidence") or 0.0),
                "sl": sl_f,
                "tp": tp_f,
                "lot": lot,
                "entry_price": entry_price,
                "fill_price": entry_price,
                "exit_price": float(exit_info["exit_price"]),
                "spread": float(exit_info.get("spread") or 0.30),
                "commission": 0.0,
                "swap": 0.0,
                "risk_percent": rec.get("risk_percent"),
                "rr": rr,
                "pnl": float(exit_info["pnl"]),
                "pnl_r": float(exit_info["pnl_r"]),
                "duration_bars": int(exit_info["duration_bars"]),
                "duration_sec": int(exit_info.get("duration_sec") or exit_info["duration_bars"] * 300),
                "mae": float(exit_info["mae"]),
                "mfe": float(exit_info["mfe"]),
                "exit_reason": str(exit_info["exit_reason"]),
                "checksum": rec.get("feature_vector_checksum"),
                "risk_allowed": rec.get("risk_allowed"),
                "risk_reason": rec.get("risk_reason"),
                "filter_diagnostics": rec.get("filter_diagnostics") or {},
                "latency_ms": rec.get("latency_ms") or {},
                "bar_index": rec.get("bar_index"),
            }
        )
    return trades
