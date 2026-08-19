"""L2 — rule-based edge discovery on fullest candles (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast

ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = ROOT / "live_l2_edge_discovery_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
FUTURE_WINDOW = 72
WARMUP = 220
STRIDE = 6
GATE_PF = 1.1
GATE_MIN_TRADES_YEAR = 30
GATE_MIN_YEARS_PASS = 3


def _pf_from_labels(labels: list[int]) -> float:
    wins = sum(1 for x in labels if x == 1)
    losses = sum(1 for x in labels if x == 0)
    if losses == 0:
        return 2.0 if wins > 0 else 0.0
    return round(wins / losses, 4)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr = _atr(high, low, close, period)
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.rolling(period).mean()


def _prepare_frame(candles: pd.DataFrame) -> pd.DataFrame:
    c = candles.copy()
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    c = c[(c.index.year >= YEAR_START) & (c.index.year <= YEAR_END)]
    o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
    c["ema20"] = _ema(cl, 20)
    c["ema50"] = _ema(cl, 50)
    c["ema200"] = _ema(cl, 200)
    c["atr14"] = _atr(h, l, cl, 14)
    c["adx14"] = _adx(h, l, cl, 14)
    c["range_high20"] = h.rolling(20).max()
    c["range_low20"] = l.rolling(20).min()
    bb_mid = cl.rolling(20).mean()
    bb_std = cl.rolling(20).std()
    c["bb_upper"] = bb_mid + 2 * bb_std
    c["bb_lower"] = bb_mid - 2 * bb_std
    c["bb_width"] = (c["bb_upper"] - c["bb_lower"]) / bb_mid.replace(0, np.nan)
    c["bb_width_pct"] = c["bb_width"].rolling(100, min_periods=50).rank(pct=True)
    c["hour_utc"] = c.index.hour
    c["year"] = c.index.year
    return c


def _resolve_trade(
    candles: pd.DataFrame,
    idx: int,
    direction: int,
    *,
    future_window: int = FUTURE_WINDOW,
) -> int | None:
    if idx < WARMUP or idx >= len(candles) - future_window - 1:
        return None
    sl, tp = production_sl_tp_at_bar_fast(candles, idx, direction)
    if sl <= 0 or tp <= 0:
        return None
    entry = float(candles["close"].iloc[idx])
    resolved = resolve_label_with_sl_tp(
        candles,
        idx,
        direction,
        sl,
        tp,
        future_window_bars=future_window,
        entry_price=entry,
    )
    label = int(resolved["label"])
    if label == int(Label.NO_RESOLUTION):
        return None
    return 1 if label == int(Label.TP_FIRST) else 0


def _scan_hypothesis(
    frame: pd.DataFrame,
    candles: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame, int], int | None],
    *,
    stride: int = STRIDE,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    indices = range(WARMUP, len(frame) - FUTURE_WINDOW - 1, stride)
    for idx in indices:
        direction = signal_fn(frame, idx)
        if direction not in (1, -1):
            continue
        outcome = _resolve_trade(candles, idx, direction)
        if outcome is None:
            continue
        trades.append(
            {
                "bar_index": idx,
                "timestamp": str(frame.index[idx]),
                "year": int(frame.index[idx].year),
                "direction": "BUY" if direction > 0 else "SELL",
                "outcome": outcome,
            }
        )
    return trades


def _trend_momentum_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    atr = float(row["atr14"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    ema20, ema50, ema200, close = float(row["ema20"]), float(row["ema50"]), float(row["ema200"]), float(row["close"])
    if not all(np.isfinite(x) for x in (ema20, ema50, ema200, close)):
        return None
    bullish = ema20 > ema50 > ema200
    bearish = ema20 < ema50 < ema200
    pullback_bull = abs(close - ema20) <= 0.35 * atr and close >= ema20
    pullback_bear = abs(close - ema20) <= 0.35 * atr and close <= ema20
    if bullish and pullback_bull:
        return 1
    if bearish and pullback_bear:
        return -1
    return None


def _range_mean_reversion_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    atr = float(row["atr14"])
    adx = float(row["adx14"])
    if not np.isfinite(atr) or atr <= 0 or not np.isfinite(adx) or adx >= 25:
        return None
    close = float(row["close"])
    rh, rl = float(row["range_high20"]), float(row["range_low20"])
    if not all(np.isfinite(x) for x in (close, rh, rl)):
        return None
    if close >= rh - 0.4 * atr:
        return -1
    if close <= rl + 0.4 * atr:
        return 1
    return None


def _breakout_squeeze_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    width_pct = float(row["bb_width_pct"])
    if not np.isfinite(width_pct) or width_pct > 0.20:
        return None
    close = float(row["close"])
    upper, lower = float(row["bb_upper"]), float(row["bb_lower"])
    if not all(np.isfinite(x) for x in (close, upper, lower)):
        return None
    if close > upper:
        return 1
    if close < lower:
        return -1
    return None


def _session_momentum_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    hour = int(row["hour_utc"])
    in_london = 7 <= hour < 10
    in_ny = 13 <= hour < 16
    if not (in_london or in_ny):
        return None
    atr = float(row["atr14"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    o, c = float(row["open"]), float(row["close"])
    body = abs(c - o)
    if body < 0.5 * atr:
        return None
    if c > o:
        return 1
    if c < o:
        return -1
    return None


HYPOTHESES: dict[str, dict[str, Any]] = {
    "TREND": {
        "title_fa": "ادامه مومنتوم روند (EMA + pullback)",
        "title_en": "Trend momentum continuation (EMA alignment + pullback)",
        "signal_fn": _trend_momentum_signal,
        "stride": STRIDE,
    },
    "RANGE": {
        "title_fa": "بازگشت به میانگین در مرز رنج",
        "title_en": "Range mean reversion at boundaries",
        "signal_fn": _range_mean_reversion_signal,
        "stride": STRIDE,
    },
    "BREAKOUT": {
        "title_fa": "شکست پس از فشردگی نوسان",
        "title_en": "Volatility squeeze breakout",
        "signal_fn": _breakout_squeeze_signal,
        "stride": STRIDE,
    },
    "SESSION": {
        "title_fa": "مومنتوم افتتاح لندن/نیویورک",
        "title_en": "London/NY open momentum",
        "signal_fn": _session_momentum_signal,
        "stride": 1,
    },
}


def _yearly_stats(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_year: dict[int, list[int]] = {}
    for t in trades:
        by_year.setdefault(t["year"], []).append(int(t["outcome"]))
    stats: dict[str, dict[str, Any]] = {}
    for year in range(YEAR_START, YEAR_END + 1):
        labels = by_year.get(year, [])
        if not labels:
            stats[str(year)] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "pf": 0.0,
                "gate_pass": False,
            }
            continue
        wins = sum(labels)
        losses = len(labels) - wins
        pf = _pf_from_labels(labels)
        stats[str(year)] = {
            "trades": len(labels),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(wins / len(labels) * 100, 2),
            "pf": pf,
            "gate_pass": pf >= GATE_PF and len(labels) >= GATE_MIN_TRADES_YEAR,
        }
    return stats


def _evaluate_gate(yearly: dict[str, dict[str, Any]]) -> dict[str, Any]:
    years_pass = sum(
        1
        for y in range(YEAR_START, YEAR_END + 1)
        if yearly.get(str(y), {}).get("gate_pass", False)
    )
    total_trades = sum(yearly.get(str(y), {}).get("trades", 0) for y in range(YEAR_START, YEAR_END + 1))
    all_labels = []
    for y in range(YEAR_START, YEAR_END + 1):
        # re-aggregate not stored per-year labels in yearly dict; use pf proxy from totals below
        pass
    return {
        "pf_threshold": GATE_PF,
        "min_trades_per_year": GATE_MIN_TRADES_YEAR,
        "min_years_pass": GATE_MIN_YEARS_PASS,
        "years_passed_gate": years_pass,
        "gate_pass": years_pass >= GATE_MIN_YEARS_PASS,
    }


def _hypothesis_report(
    hyp_id: str,
    meta: dict[str, Any],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    yearly = _yearly_stats(trades)
    gate = _evaluate_gate(yearly)
    labels = [int(t["outcome"]) for t in trades]
    wins = sum(labels)
    losses = len(labels) - wins
    return {
        "id": hyp_id,
        "title_fa": meta["title_fa"],
        "title_en": meta["title_en"],
        "stride": meta["stride"],
        "total_trades": len(trades),
        "overall_pf": _pf_from_labels(labels) if labels else 0.0,
        "overall_win_rate_pct": round(wins / len(labels) * 100, 2) if labels else 0.0,
        "yearly": yearly,
        "gate": gate,
        "honest_edge": gate["gate_pass"],
    }


def run_edge_discovery(
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
    stride_override: int | None = None,
) -> dict[str, Any]:
    global YEAR_START, YEAR_END, STRIDE
    YEAR_START, YEAR_END = year_start, year_end
    if stride_override is not None:
        STRIDE = stride_override

    candles = resolve_fullest_candles(symbol, timeframe)
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "error": "fullest candle source missing"}

    frame = _prepare_frame(candles)
    candle_audit = {
        "rows_total": len(candles),
        "rows_in_window": len(frame),
        "start": str(frame.index.min()) if len(frame) else None,
        "end": str(frame.index.max()) if len(frame) else None,
        "source": "phase39.resolve_fullest_candles",
    }

    results: list[dict[str, Any]] = []
    for hyp_id, meta in HYPOTHESES.items():
        stride = meta["stride"] if stride_override is None else stride_override
        print(f"L2: scanning {hyp_id} stride={stride} ...", flush=True)
        trades = _scan_hypothesis(frame, candles, meta["signal_fn"], stride=stride)
        results.append(_hypothesis_report(hyp_id, {**meta, "stride": stride}, trades))
        print(
            f"  {hyp_id}: trades={len(trades)} pf={results[-1]['overall_pf']} gate={results[-1]['honest_edge']}",
            flush=True,
        )

    results.sort(
        key=lambda r: (
            r["honest_edge"],
            r["overall_pf"],
            r["total_trades"],
        ),
        reverse=True,
    )

    any_edge = any(r["honest_edge"] for r in results)
    return {
        "phase": "L2",
        "title": "Edge Discovery",
        "title_fa": "کشف لبه قانون‌محور",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "EDGE_FOUND" if any_edge else "NO_HONEST_EDGE",
        "research_only": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "year_range": [year_start, year_end],
        "label_resolution": "phase35.resolve_label_with_sl_tp + production_sl_tp_at_bar_fast",
        "candle_source": candle_audit,
        "methodology": {
            "stride_default": STRIDE,
            "future_window_bars": FUTURE_WINDOW,
            "gate_pf": GATE_PF,
            "gate_min_trades_year": GATE_MIN_TRADES_YEAR,
            "gate_min_years": GATE_MIN_YEARS_PASS,
            "sampling_note_fa": "stride>1 برای کارایی؛ نتایج صادقانه و بدون look-ahead",
            "sampling_note_en": "stride>1 for efficiency; honest forward resolution, no look-ahead",
        },
        "hypotheses": results,
        "ranking": [r["id"] for r in results],
        "best_hypothesis": results[0]["id"] if results else None,
        "any_honest_edge": any_edge,
        "recommendation_fa": (
            "حداقل یک فرضیه gate را پاس کرد — ادامه L3"
            if any_edge
            else "هیچ فرضیه‌ای gate صادقانه را پاس نکرد — ادامه L2 با فرضیه‌های جدید"
        ),
        "recommendation_en": (
            "At least one hypothesis passed gate — proceed to L3"
            if any_edge
            else "No hypothesis passed honest gate — continue L2 with new hypotheses"
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_edge_discovery()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
