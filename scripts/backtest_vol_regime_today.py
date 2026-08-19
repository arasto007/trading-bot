#!/usr/bin/env python3
"""VOL_REGIME backtest for a fixed UTC calendar day (default: today)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from scripts.backtest_vol_regime_24h import (  # noqa: E402
    CONFIG_ID,
    DEFAULT_ATR_SL_MULT,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    DEFAULT_TP_RR,
    STRATEGY_ID,
    _passes_tq,
    _resolve_r,
)
from tradingbot.ml.research.live_l2.edge_discovery import FUTURE_WINDOW  # noqa: E402
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (  # noqa: E402
    _prepare_frame_round2,
    _volatility_regime_signal,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import _make_sl_tp_fn  # noqa: E402
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp  # noqa: E402
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles  # noqa: E402


def run_backtest_day(*, day: str, refresh: bool = False) -> dict:
    if refresh:
        try:
            from tradingbot.ml.research.live_l5.refresh_live_candles import refresh_live_candles

            refresh_live_candles()
        except Exception as exc:
            print(f"WARN | candle refresh skipped: {exc}", flush=True)

    day_start = pd.Timestamp(f"{day} 00:00:00", tz="UTC")
    day_end = pd.Timestamp(datetime.now(timezone.utc))

    candles = resolve_fullest_candles(DEFAULT_SYMBOL, DEFAULT_TIMEFRAME)
    if candles is None or candles.empty:
        raise RuntimeError("No candle data for backtest")

    candles = candles.copy()
    candles.index = pd.to_datetime(candles.index, utc=True)
    candles = candles.sort_index()

    end = min(day_end, candles.index.max())
    start = day_start
    if end < start:
        raise RuntimeError(f"No candle data in window {start} -> {end}")

    frame_full = _prepare_frame_round2(candles)
    if frame_full.empty:
        raise RuntimeError("Empty indicator frame")

    sl_tp_fn = _make_sl_tp_fn("atr_rr", atr_mult=DEFAULT_ATR_SL_MULT, rr=DEFAULT_TP_RR)

    trades: list[dict] = []
    blocked_tq = 0
    next_idx = 0

    for idx in range(len(frame_full)):
        ts = pd.Timestamp(frame_full.index[idx])
        if ts < start or ts > end:
            continue
        if idx < next_idx:
            continue
        direction = _volatility_regime_signal(frame_full, idx)
        if direction not in (1, -1):
            continue
        direction_str = "BUY" if direction > 0 else "SELL"
        allowed, tq_score = _passes_tq(frame_full, idx, direction_str)
        if not allowed:
            blocked_tq += 1
            continue

        entry = float(candles["close"].iloc[idx])
        atr = float(frame_full["atr14"].iloc[idx])
        sl, tp = sl_tp_fn(entry, direction, atr)
        if sl <= 0 or tp <= 0:
            continue

        r_mult, outcome = _resolve_r(candles, idx, direction, sl, tp)
        if r_mult is None:
            continue

        resolved = resolve_label_with_sl_tp(
            candles,
            idx,
            direction,
            sl,
            tp,
            future_window_bars=FUTURE_WINDOW,
            entry_price=entry,
        )
        exit_bars = int(resolved.get("bars", FUTURE_WINDOW))
        next_idx = idx + max(1, exit_bars)

        trades.append(
            {
                "timestamp": ts.isoformat(),
                "direction": direction_str,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "r": r_mult,
                "outcome": outcome,
                "tq_score": round(tq_score, 4),
                "bar_index": idx,
            }
        )

    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    net_r = float(sum(t["r"] for t in trades))
    gross_win = float(sum(t["r"] for t in trades if t["r"] > 0))
    gross_loss = abs(float(sum(t["r"] for t in trades if t["r"] < 0)))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    hours = (end - start).total_seconds() / 3600.0

    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": STRATEGY_ID,
        "config_id": CONFIG_ID,
        "symbol": DEFAULT_SYMBOL,
        "timeframe": DEFAULT_TIMEFRAME,
        "window_hours": round(hours, 4),
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "window_label": f"{day} calendar day UTC",
        "atr_sl_mult": DEFAULT_ATR_SL_MULT,
        "tp_rr": DEFAULT_TP_RR,
        "ml_filter": "SKIP",
        "tq_path": "production_vol_regime",
        "trades_total": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100.0 * wins / len(trades), 2) if trades else 0.0,
        "profit_factor": round(pf, 4),
        "net_r": round(net_r, 4),
        "blocked_by_tq": blocked_tq,
        "trades": trades,
    }


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="VOL_REGIME calendar-day backtest")
    parser.add_argument("--day", default=today, help="UTC calendar day YYYY-MM-DD")
    parser.add_argument("--refresh", action="store_true", help="Refresh candles from MT5 first")
    parser.add_argument(
        "--output",
        default="",
        help="Report JSON path (default logs/backtest_today_<day>.json)",
    )
    args = parser.parse_args()

    report = run_backtest_day(day=args.day, refresh=args.refresh)
    out = Path(args.output) if args.output else ROOT / "logs" / f"backtest_today_{args.day}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"=== VOL_REGIME Today Backtest ({args.day}) ===")
    print(f"Window: {report['window_start_utc']} -> {report['window_end_utc']}")
    print(f"Trades: {report['trades_total']} | Wins: {report['wins']} | Losses: {report['losses']}")
    print(f"PF: {report['profit_factor']} | Net R: {report['net_r']}")
    print(f"TQ blocked signals: {report['blocked_by_tq']}")
    print(f"Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
