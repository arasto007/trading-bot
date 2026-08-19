#!/usr/bin/env python3
"""24-hour VOL_REGIME backtest — XAUUSD M5, ATR2.5_RR0.8, production TQ path."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from tradingbot.ml.dataset.schema import Label  # noqa: E402
from tradingbot.ml.research.live_l2.edge_discovery import FUTURE_WINDOW  # noqa: E402
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (  # noqa: E402
    _prepare_frame_round2,
    _volatility_regime_signal,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import _make_sl_tp_fn  # noqa: E402
from tradingbot.ml.research.live_l3.execution_validation import (  # noqa: E402
    _infer_regime,
    _session_from_row,
    _spread_pips,
)
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp  # noqa: E402
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles  # noqa: E402
from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics, RiskRecommendation  # noqa: E402
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine  # noqa: E402
from tradingbot.ml.trade_quality.quality_types import TradeQualityContext  # noqa: E402
from tradingbot.ml.trade_quality.regime_quality import VOL_REGIME_ENGINE  # noqa: E402
from tradingbot.strategies.vol_regime_signal import (  # noqa: E402
    CONFIG_ID,
    DEFAULT_ATR_SL_MULT,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    DEFAULT_TP_RR,
    STRATEGY_ID,
)

REPORT_PATH = ROOT / "logs" / "backtest_24h_report.json"


def _passes_tq(frame: pd.DataFrame, idx: int, direction_str: str) -> tuple[bool, float]:
    row = frame.iloc[idx]
    regime = _infer_regime(row)
    risk = RiskRecommendation(
        allowed=True,
        risk_percent=1.0,
        multiplier=1.0,
        confidence_factor=1.0,
        regime_factor=1.0,
        volatility_factor=1.0,
        session_factor=1.0,
        drawdown_factor=1.0,
        reason="backtest production TQ path",
        trace=["backtest vol_regime"],
    )
    ctx = TradeQualityContext(
        market=None,  # type: ignore[arg-type]
        calibrated=None,  # type: ignore[arg-type]
        risk=risk,
        engine=VOL_REGIME_ENGINE,
        regime=regime,
        action=direction_str,
        confidence=0.60,
        risk_percent=1.0,
        atr_percentile=float(row.get("atr_pct", 0.5)),
        spread_pips=_spread_pips(row),
        spread_class="NORMAL",
        session=_session_from_row(row),
        rr_ratio=DEFAULT_TP_RR,
    )
    quality = TradeQualityEngine(history=HistoricalMetrics()).evaluate(ctx)
    return quality.allowed, quality.score


def _resolve_r(
    candles: pd.DataFrame,
    idx: int,
    direction: int,
    sl: float,
    tp: float,
) -> tuple[float | None, str]:
    resolved = resolve_label_with_sl_tp(
        candles,
        idx,
        direction,
        sl,
        tp,
        future_window_bars=FUTURE_WINDOW,
        entry_price=float(candles["close"].iloc[idx]),
    )
    label = int(resolved["label"])
    if label == int(Label.TP_FIRST):
        return DEFAULT_TP_RR, "win"
    if label == int(Label.SL_FIRST):
        return -1.0, "loss"
    return None, "timeout"


def run_backtest(*, hours: float = 24.0, refresh: bool = False) -> dict:
    if refresh:
        try:
            from tradingbot.ml.research.live_l5.refresh_live_candles import refresh_live_candles

            refresh_live_candles()
        except Exception as exc:
            print(f"WARN | candle refresh skipped: {exc}", flush=True)

    candles = resolve_fullest_candles(DEFAULT_SYMBOL, DEFAULT_TIMEFRAME)
    if candles is None or candles.empty:
        raise RuntimeError("No candle data for backtest")

    candles = candles.copy()
    candles.index = pd.to_datetime(candles.index, utc=True)
    candles = candles.sort_index()

    end = candles.index.max()
    start = end - timedelta(hours=hours)
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

        exit_bars = FUTURE_WINDOW
        resolved = resolve_label_with_sl_tp(
            candles, idx, direction, sl, tp, future_window_bars=FUTURE_WINDOW, entry_price=entry,
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

    report = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": STRATEGY_ID,
        "config_id": CONFIG_ID,
        "symbol": DEFAULT_SYMBOL,
        "timeframe": DEFAULT_TIMEFRAME,
        "window_hours": hours,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
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
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="VOL_REGIME 24h backtest")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--refresh", action="store_true", help="Refresh candles from MT5 first")
    parser.add_argument(
        "--output",
        default=str(REPORT_PATH),
        help="Report JSON path",
    )
    args = parser.parse_args()

    report = run_backtest(hours=args.hours, refresh=args.refresh)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"=== VOL_REGIME {args.hours}h Backtest ===")
    print(f"Window: {report['window_start_utc']} -> {report['window_end_utc']}")
    print(f"Trades: {report['trades_total']} | Wins: {report['wins']} | Losses: {report['losses']}")
    print(f"PF: {report['profit_factor']} | Net R: {report['net_r']}")
    print(f"TQ blocked signals: {report['blocked_by_tq']}")
    print(f"Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
