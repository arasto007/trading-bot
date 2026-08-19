"""L2 round 2 — expanded rule-based edge hypotheses (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.live_l2.edge_discovery import (
    FUTURE_WINDOW,
    GATE_MIN_TRADES_YEAR,
    GATE_PF,
    STRIDE,
    WARMUP,
    _atr,
    _ema,
    _evaluate_gate,
    _hypothesis_report,
    _pf_from_labels,
    _resolve_trade,
    _scan_hypothesis,
    _yearly_stats,
)
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast

ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = ROOT / "live_l2_edge_discovery_round2_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
GATE_MIN_YEARS_PASS = 3
MARGINAL_PF = 0.9
MARGINAL_MIN_YEARS = 2


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _session_label(hour: int) -> str:
    if 7 <= hour < 12:
        return "london"
    if 13 <= hour < 17:
        return "new_york"
    if 0 <= hour < 7:
        return "asia"
    return "off_hours"


def _spread_proxy_pips(row: pd.Series) -> float:
    close = float(row["close"])
    if close <= 0:
        return np.nan
    return float((row["high"] - row["low"]) / close * 10000.0)


def _build_h1_trend(m5: pd.DataFrame) -> pd.Series:
    h1 = (
        m5[["open", "high", "low", "close"]]
        .resample("1h", label="right", closed="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )
    h1["ema50"] = _ema(h1["close"], 50)
    h1["ema200"] = _ema(h1["close"], 200)
    h1["trend"] = np.where(
        h1["ema50"] > h1["ema200"],
        1,
        np.where(h1["ema50"] < h1["ema200"], -1, 0),
    )
    return h1["trend"].reindex(m5.index, method="ffill").fillna(0).astype(int)


def _session_vwap(m5: pd.DataFrame) -> pd.Series:
    typical = (m5["high"] + m5["low"] + m5["close"]) / 3.0
    vol = m5["volume"].replace(0, np.nan).fillna(1.0)
    day = m5.index.floor("D")
    cum_pv = (typical * vol).groupby(day).cumsum()
    cum_v = vol.groupby(day).cumsum()
    return cum_pv / cum_v.replace(0, np.nan)


def _prepare_frame_round2(candles: pd.DataFrame) -> pd.DataFrame:
    c = candles.copy()
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    c = c[(c.index.year >= YEAR_START) & (c.index.year <= YEAR_END)]
    o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
    c["ema20"] = _ema(cl, 20)
    c["ema50"] = _ema(cl, 50)
    c["ema200"] = _ema(cl, 200)
    c["atr14"] = _atr(h, l, cl, 14)
    c["atr_pct"] = c["atr14"].rolling(500, min_periods=100).rank(pct=True)
    c["rsi14"] = _rsi(cl, 14)
    c["h1_trend"] = _build_h1_trend(c)
    c["vwap"] = _session_vwap(c)
    c["spread_proxy"] = c.apply(_spread_proxy_pips, axis=1)
    c["spread_pct"] = c["spread_proxy"].rolling(200, min_periods=50).rank(pct=True)
    c["hour_utc"] = c.index.hour
    c["minute_utc"] = c.index.minute
    c["session"] = c["hour_utc"].map(_session_label)
    c["year"] = c.index.year
    c["swing_high20"] = h.rolling(20).max().shift(1)
    c["swing_low20"] = l.rolling(20).min().shift(1)
    c["prev_close"] = cl.shift(1)
    c["ny_open_move"] = cl - cl.shift(12)
    return c


def _multi_tf_trend_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    trend = int(row["h1_trend"])
    if trend == 0:
        return None
    atr = float(row["atr14"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    close, ema20 = float(row["close"]), float(row["ema20"])
    if not np.isfinite(close) or not np.isfinite(ema20):
        return None
    if trend > 0 and close >= ema20 and abs(close - ema20) <= 0.5 * atr:
        return 1
    if trend < 0 and close <= ema20 and abs(close - ema20) <= 0.5 * atr:
        return -1
    return None


def _volatility_regime_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    atr_pct = float(row["atr_pct"])
    if not np.isfinite(atr_pct) or not (0.30 <= atr_pct <= 0.70):
        return None
    ema20, ema50, close = float(row["ema20"]), float(row["ema50"]), float(row["close"])
    if not all(np.isfinite(x) for x in (ema20, ema50, close)):
        return None
    if ema20 > ema50 and close > ema20:
        return 1
    if ema20 < ema50 and close < ema20:
        return -1
    return None


def _pullback_vwap_rsi_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    atr = float(row["atr14"])
    rsi = float(row["rsi14"])
    if not np.isfinite(atr) or atr <= 0 or not np.isfinite(rsi):
        return None
    close, vwap, ema50 = float(row["close"]), float(row["vwap"]), float(row["ema50"])
    if not all(np.isfinite(x) for x in (close, vwap, ema50)):
        return None
    bullish = close > ema50 and close >= vwap - 0.25 * atr and close <= vwap + 0.15 * atr
    bearish = close < ema50 and close <= vwap + 0.25 * atr and close >= vwap - 0.15 * atr
    if bullish and 40 <= rsi <= 58:
        return 1
    if bearish and 42 <= rsi <= 60:
        return -1
    return None


def _london_killzone_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    hour, minute = int(row["hour_utc"]), int(row["minute_utc"])
    if not (7 <= hour < 9 or (hour == 9 and minute == 0)):
        return None
    atr = float(row["atr14"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    o, c = float(row["open"]), float(row["close"])
    body = abs(c - o)
    if body < 0.45 * atr:
        return None
    if c > o:
        return 1
    if c < o:
        return -1
    return None


def _ny_reversal_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    hour, minute = int(row["hour_utc"]), int(row["minute_utc"])
    if not (13 <= hour < 14 or (hour == 14 and minute <= 30)):
        return None
    move = float(row["ny_open_move"])
    atr = float(row["atr14"])
    if not np.isfinite(move) or not np.isfinite(atr) or atr <= 0:
        return None
    if move >= 1.2 * atr:
        return -1
    if move <= -1.2 * atr:
        return 1
    return None


def _bos_retest_signal(frame: pd.DataFrame, idx: int) -> int | None:
    if idx < 25:
        return None
    row = frame.iloc[idx]
    prev = frame.iloc[idx - 1]
    sh, sl = float(row["swing_high20"]), float(row["swing_low20"])
    close, prev_close = float(row["close"]), float(prev["close"])
    atr = float(row["atr14"])
    if not all(np.isfinite(x) for x in (sh, sl, close, prev_close, atr)) or atr <= 0:
        return None
    broke_up = prev_close > sh and close <= sh + 0.35 * atr and close >= sh - 0.15 * atr
    broke_dn = prev_close < sl and close >= sl - 0.35 * atr and close <= sl + 0.15 * atr
    if broke_up:
        return 1
    if broke_dn:
        return -1
    return None


def _spread_session_filter_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    spread_pct = float(row["spread_pct"])
    session = str(row["session"])
    if not np.isfinite(spread_pct) or spread_pct > 0.35:
        return None
    if session not in ("london", "new_york"):
        return None
    atr = float(row["atr14"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    ema20, ema50, close = float(row["ema20"]), float(row["ema50"]), float(row["close"])
    if not all(np.isfinite(x) for x in (ema20, ema50, close)):
        return None
    if ema20 > ema50 and close > ema20:
        return 1
    if ema20 < ema50 and close < ema20:
        return -1
    return None


HYPOTHESES_R2: dict[str, dict[str, Any]] = {
    "MULTI_TF_TREND": {
        "title_fa": "روند H1 + ورود M5 (EMA50/200)",
        "title_en": "Multi-TF trend: H1 EMA50/200 filter + M5 pullback entry",
        "signal_fn": _multi_tf_trend_signal,
        "stride": STRIDE,
    },
    "VOL_REGIME": {
        "title_fa": "رژیم نوسان ATR 30-70%",
        "title_en": "Volatility regime: ATR percentile sweet spot 30-70%",
        "signal_fn": _volatility_regime_signal,
        "stride": STRIDE,
    },
    "PULLBACK_VWAP": {
        "title_fa": "پولبک VWAP/EMA + فیلتر RSI",
        "title_en": "Pullback to VWAP/EMA with RSI filter",
        "signal_fn": _pullback_vwap_rsi_signal,
        "stride": STRIDE,
    },
    "LONDON_KZ": {
        "title_fa": "دو ساعت اول لندن (kill zone)",
        "title_en": "London kill zone: first 2 hours only",
        "signal_fn": _london_killzone_signal,
        "stride": 1,
    },
    "NY_REVERSAL": {
        "title_fa": "برگشت NY در حرکت کشیده",
        "title_en": "NY open reversal fade extended move",
        "signal_fn": _ny_reversal_signal,
        "stride": 2,
    },
    "BOS_RETEST": {
        "title_fa": "شکست ساختار + ریتست (ICT ساده)",
        "title_en": "Structure break + retest (simplified ICT BOS)",
        "signal_fn": _bos_retest_signal,
        "stride": STRIDE,
    },
    "SPREAD_SESSION": {
        "title_fa": "فیلتر spread پایین + session لندن/NY",
        "title_en": "Low spread proxy + London/NY session filter",
        "signal_fn": _spread_session_filter_signal,
        "stride": STRIDE,
    },
}


def _marginal_years(yearly: dict[str, dict[str, Any]]) -> int:
    count = 0
    for year in range(YEAR_START, YEAR_END + 1):
        y = yearly.get(str(year), {})
        if y.get("trades", 0) >= GATE_MIN_TRADES_YEAR and y.get("pf", 0) >= MARGINAL_PF:
            count += 1
    return count


def _hypothesis_report_r2(
    hyp_id: str,
    meta: dict[str, Any],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    base = _hypothesis_report(hyp_id, meta, trades)
    yearly = base["yearly"]
    marginal_years = _marginal_years(yearly)
    base["marginal_edge"] = marginal_years >= MARGINAL_MIN_YEARS
    base["marginal_years_pf_ge_0_9"] = marginal_years
    base["marginal_threshold_pf"] = MARGINAL_PF
    base["marginal_min_years"] = MARGINAL_MIN_YEARS
    return base


def _combo_signal(
    frame: pd.DataFrame,
    idx: int,
    fns: list[Callable[[pd.DataFrame, int], int | None]],
) -> int | None:
    directions: list[int] = []
    for fn in fns:
        d = fn(frame, idx)
        if d in (1, -1):
            directions.append(d)
    if len(directions) != len(fns):
        return None
    if len(set(directions)) != 1:
        return None
    return directions[0]


def _build_combinations(
    frame: pd.DataFrame,
    candles: pd.DataFrame,
    ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    marginal = [r for r in ranked if r.get("marginal_edge")]
    if len(marginal) < 2:
        return []
    top2 = marginal[:2]
    fns = [HYPOTHESES_R2[r["id"]]["signal_fn"] for r in top2]
    combo_id = f"COMBO_{top2[0]['id']}_{top2[1]['id']}"
    stride = max(HYPOTHESES_R2[r["id"]]["stride"] for r in top2)
    trades = _scan_hypothesis(
        frame,
        candles,
        lambda fr, ix: _combo_signal(fr, ix, fns),
        stride=stride,
    )
    meta = {
        "title_fa": f"ترکیب {top2[0]['id']} + {top2[1]['id']}",
        "title_en": f"Combined: {top2[0]['id']} AND {top2[1]['id']}",
        "stride": stride,
        "components": [r["id"] for r in top2],
    }
    return [_hypothesis_report_r2(combo_id, meta, trades)]


def run_edge_discovery_round2(
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
    stride_override: int | None = None,
) -> dict[str, Any]:
    global YEAR_START, YEAR_END
    YEAR_START, YEAR_END = year_start, year_end

    candles = resolve_fullest_candles(symbol, timeframe)
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "error": "fullest candle source missing"}

    frame = _prepare_frame_round2(candles)
    candle_audit = {
        "rows_total": len(candles),
        "rows_in_window": len(frame),
        "start": str(frame.index.min()) if len(frame) else None,
        "end": str(frame.index.max()) if len(frame) else None,
        "source": "phase39.resolve_fullest_candles",
        "spread_column_present": "spread_pips" in candles.columns,
        "spread_proxy_used": True,
    }

    results: list[dict[str, Any]] = []
    for hyp_id, meta in HYPOTHESES_R2.items():
        stride = meta["stride"] if stride_override is None else stride_override
        print(f"L2r2: scanning {hyp_id} stride={stride} ...", flush=True)
        trades = _scan_hypothesis(frame, candles, meta["signal_fn"], stride=stride)
        results.append(_hypothesis_report_r2(hyp_id, {**meta, "stride": stride}, trades))
        print(
            f"  {hyp_id}: trades={len(trades)} pf={results[-1]['overall_pf']} "
            f"gate={results[-1]['honest_edge']} marginal={results[-1]['marginal_edge']}",
            flush=True,
        )

    results.sort(
        key=lambda r: (r["honest_edge"], r["marginal_edge"], r["overall_pf"], r["total_trades"]),
        reverse=True,
    )

    combos = _build_combinations(frame, candles, results)
    for combo in combos:
        print(
            f"  {combo['id']}: trades={combo['total_trades']} pf={combo['overall_pf']} "
            f"gate={combo['honest_edge']}",
            flush=True,
        )
    results.extend(combos)

    any_edge = any(r["honest_edge"] for r in results)
    any_marginal = any(r.get("marginal_edge") for r in results)
    round3_candidates = [r["id"] for r in results if r.get("marginal_edge")][:2]

    return {
        "phase": "L2r2",
        "title": "Edge Discovery Round 2",
        "title_fa": "کشف لبه — دور دوم (فرضیه‌های گسترده)",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "EDGE_FOUND" if any_edge else ("MARGINAL_EDGE" if any_marginal else "NO_HONEST_EDGE"),
        "research_only": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "year_range": [year_start, year_end],
        "label_resolution": "phase35.resolve_label_with_sl_tp + production_sl_tp_at_bar_fast",
        "candle_source": candle_audit,
        "methodology": {
            "round": 2,
            "stride_default": STRIDE,
            "future_window_bars": FUTURE_WINDOW,
            "gate_pf": GATE_PF,
            "gate_min_trades_year": GATE_MIN_TRADES_YEAR,
            "gate_min_years": GATE_MIN_YEARS_PASS,
            "marginal_pf": MARGINAL_PF,
            "marginal_min_years": MARGINAL_MIN_YEARS,
            "round1_reference": "live_l2_edge_discovery_report.json",
        },
        "hypotheses": results,
        "ranking": [r["id"] for r in sorted(results, key=lambda x: x["overall_pf"], reverse=True)],
        "best_hypothesis": max(results, key=lambda r: r["overall_pf"])["id"] if results else None,
        "any_honest_edge": any_edge,
        "any_marginal_edge": any_marginal,
        "round3_combo_candidates": round3_candidates,
        "recommendation_fa": (
            "حداقل یک فرضیه gate را پاس کرد — ادامه L3"
            if any_edge
            else (
                "لبه ضعیف (PF≥0.9 در 2+ سال) — ادامه L2r3 با ترکیب"
                if any_marginal
                else "هیچ فرضیه‌ای gate یا لبه ضعیف را پاس نکرد — رویکرد متفاوت لازم است"
            )
        ),
        "recommendation_en": (
            "At least one hypothesis passed gate — proceed to L3"
            if any_edge
            else (
                "Marginal edge (PF≥0.9 in 2+ years) — proceed L2r3 combo"
                if any_marginal
                else "No hypothesis passed honest or marginal gate — need different approach"
            )
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_edge_discovery_round2()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
