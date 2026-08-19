"""Phase 22F — representative dataset creation and balance verification."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase22f.config import SYMBOL, RapidDataset, configure_research_env


def _session_label(ts: pd.Timestamp) -> str:
    h = ts.hour
    if 0 <= h < 7:
        return "asian"
    if 7 <= h < 12:
        return "london"
    if 12 <= h < 17:
        return "new_york"
    return "off_hours"


def _adx_proxy(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean()
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_di = 100 * pd.Series(plus_dm, index=close.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.rolling(period).mean()


def _regime_proxy(adx: float, atr_pct: float) -> str:
    if adx >= 25:
        return "trend"
    if atr_pct >= 0.0015:
        return "volatile_range"
    return "range"


async def load_ohlcv_for_dataset(dataset: RapidDataset, timeframe: str = "M5") -> pd.DataFrame | None:
    configure_research_env()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.data_source import BacktestMarketData
    from tradingbot.ml.research.phase22f.config import TEHRAN, data_window_days

    legacy = load_legacy_config()
    now_tehran = datetime.now(TEHRAN)
    days, offset = data_window_days(timeframe, dataset.start, dataset.end, now_tehran)
    bc = BacktestConfig(
        symbols=[SYMBOL],
        timeframe=timeframe,
        days=days,
        start_offset_days=offset,
        use_cache=True,
    )
    try:
        md = Mt5MarketDataAdapter(legacy)
        await md.ensure_connected()
    except Exception:
        pass
    ds = BacktestMarketData(bc, legacy)
    ds.load()
    frame = ds.frame(SYMBOL)
    if frame is None or frame.empty:
        return None
    idx = pd.to_datetime(frame.index, utc=True)
    frame = frame.copy()
    frame.index = idx
    mask = (frame.index >= pd.Timestamp(dataset.start.astimezone(idx.tz))) & (
        frame.index <= pd.Timestamp(dataset.end.astimezone(idx.tz))
    )
    return frame.loc[mask] if mask.any() else frame.tail(min(len(frame), 500))


def characterize_frame(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"bars": 0, "error": "no_data"}

    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    adx = _adx_proxy(high, low, close).fillna(0)
    atr_pct = ((high - low) / close.replace(0, np.nan)).fillna(0)

    sessions: dict[str, int] = {}
    regimes: dict[str, int] = {}
    for ts, row_adx, row_atr in zip(frame.index, adx, atr_pct):
        sessions[_session_label(ts)] = sessions.get(_session_label(ts), 0) + 1
        rg = _regime_proxy(float(row_adx), float(row_atr))
        regimes[rg] = regimes.get(rg, 0) + 1

    total = len(frame)
    session_pct = {k: round(v / total * 100, 2) for k, v in sessions.items()}
    regime_pct = {k: round(v / total * 100, 2) for k, v in regimes.items()}

    return {
        "bars": total,
        "sessions": sessions,
        "session_pct": session_pct,
        "regimes": regimes,
        "regime_pct": regime_pct,
        "adx_median": round(float(adx.median()), 2),
        "atr_pct_median": round(float(atr_pct.median()), 6),
    }


def verify_balance(char: dict[str, Any]) -> dict[str, Any]:
    if char.get("bars", 0) < 50:
        return {"balanced": False, "reason": "insufficient_bars", **char}

    session_pct = char.get("session_pct", {})
    regime_pct = char.get("regime_pct", {})
    checks = {
        "has_asian": session_pct.get("asian", 0) >= 5,
        "has_london": session_pct.get("london", 0) >= 10,
        "has_new_york": session_pct.get("new_york", 0) >= 10,
        "has_trend": regime_pct.get("trend", 0) >= 5,
        "has_range": regime_pct.get("range", 0) + regime_pct.get("volatile_range", 0) >= 20,
        "has_volatile": regime_pct.get("volatile_range", 0) >= 3,
    }
    return {
        "balanced": all(checks.values()),
        "checks": checks,
        **char,
    }


async def build_all_datasets(end=None) -> dict[str, Any]:
    from tradingbot.ml.research.phase22f.config import build_dataset

    out: dict[str, Any] = {"phase": "22F", "datasets": {}}
    for label in ("A", "B", "C"):
        ds = build_dataset(label, end=end)
        frame = await load_ohlcv_for_dataset(ds, "M5")
        char = characterize_frame(frame) if frame is not None else {"bars": 0}
        verified = verify_balance(char)
        out["datasets"][label] = {
            "definition": ds.to_dict(),
            "characterization": verified,
        }
    return out
