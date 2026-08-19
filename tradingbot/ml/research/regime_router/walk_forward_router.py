"""Phase 13.5 — chronological router backtest and walk-forward windows."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify
from tradingbot.ml.research.regime_detector.regime_features import compute_regime_features_from_candles
from tradingbot.ml.research.regime_router.config import MAX_HOLD_BARS, RouterConfig, WALK_FORWARD_YEARS
from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
from tradingbot.ml.research.regime_router.regime_router import route_bar
from tradingbot.ml.research.regime_router.signal_aggregator import aggregate_signal
from tradingbot.ml.research.regime_router.trend_engine_adapter import TrendEngineAdapter
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features


def build_year_windows() -> list[dict[str, Any]]:
    return [{"window_id": f"wf_{year}", "test_year": year} for year in WALK_FORWARD_YEARS]


def _year_mask(ts: pd.Series, year: int) -> np.ndarray:
    return pd.to_datetime(ts, utc=True).dt.year.to_numpy() == year


def _prior_years_mask(ts: pd.Series, year: int) -> np.ndarray:
    return pd.to_datetime(ts, utc=True).dt.year.to_numpy() < year


def _simulate_trade(
    work: pd.DataFrame,
    i: int,
    *,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> tuple[str, float, float, int]:
    n = len(work)
    exit_bar = min(i + MAX_HOLD_BARS, n - 1)
    r_unit = abs(entry - sl)
    for j in range(i + 1, exit_bar + 1):
        bar = work.iloc[j]
        hi = float(bar["high"])
        lo = float(bar["low"])
        if direction == "BUY":
            if lo <= sl:
                return "SL", sl, -1.0, j
            if hi >= tp:
                return "TP", tp, 2.0, j
        else:
            if hi >= sl:
                return "SL", sl, -1.0, j
            if lo <= tp:
                return "TP", tp, 2.0, j
        exit_price = float(bar["close"])
    if direction == "BUY":
        r_mult = (exit_price - entry) / r_unit if r_unit > 0 else 0.0
    else:
        r_mult = (entry - exit_price) / r_unit if r_unit > 0 else 0.0
    return "TIMEOUT", exit_price, r_mult, exit_bar


def run_router_backtest(
    candles: pd.DataFrame,
    *,
    config: RouterConfig,
    base_dir: str | None = None,
    range_adapter: RangeEngineAdapter | None = None,
    trend_adapter: TrendEngineAdapter | None = None,
    dataset: pd.DataFrame | None = None,
    initial_equity: float = 10_000.0,
) -> dict[str, Any]:
    """Chronological multi-regime research backtest."""
    regime_frame = compute_regime_features_from_candles(candles)
    trend_frame = build_ml_features(candles)
    merged = trend_frame.merge(regime_frame, on="timestamp", how="left", suffixes=("", "_reg"))
    merged = _merge_range_features(merged, dataset)
    merged = merged.sort_values("timestamp").reset_index(drop=True)

    range_engine = range_adapter or RangeEngineAdapter.load(symbol=config.symbol, base_dir=base_dir)
    trend_engine = trend_adapter or TrendEngineAdapter.load(
        candles, symbol=config.symbol, base_dir=base_dir, seed=config.seed, threshold=config.trend_ml_threshold
    )

    regimes = rule_classify(merged)
    trades: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    equity = initial_equity
    i = 0
    n = len(merged)
    candle_index_map = _candle_index_map(candles)

    while i < n - 1:
        row = merged.iloc[i]
        regime = str(regimes.iloc[i])
        range_out = trend_out = None
        ts = pd.Timestamp(row["timestamp"])
        bar_index = candle_index_map.get(ts)

        if regime == "RANGE" and bar_index is not None:
            range_out = range_engine.evaluate(row=row, candles=candles, bar_index=bar_index)
        elif regime == "TREND":
            trend_out = trend_engine.evaluate(row, regime=regime)
        elif regime in ("HIGH_VOLATILITY", "NO_TRADE"):
            trades.append(
                {
                    "type": "block",
                    "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                    "regime": regime,
                    "source_engine": None,
                }
            )

        routed = route_bar(regime, range_output=range_out, trend_output=trend_out)
        aggregated = aggregate_signal(routed, risk_pct=config.risk_pct, rr_ratio=config.rr_ratio)
        decisions.append(
            {
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "regime": regime,
                "final_signal": aggregated["final_signal"],
                "source_engine": aggregated.get("source_engine"),
            }
        )

        signal = aggregated["final_signal"]
        if signal not in ("BUY", "SELL"):
            i += 1
            continue

        risk = aggregated["risk_parameters"]
        entry = float(risk.get("entry") or row["close"])
        sl = float(risk["sl"])
        tp = float(risk["tp"])
        risk_amount = equity * float(risk.get("risk_pct", config.risk_pct))
        result, exit_price, r_mult, exit_bar = _simulate_trade(merged, i, direction=signal, entry=entry, sl=sl, tp=tp)
        pnl = r_mult * risk_amount
        equity += pnl
        trades.append(
            {
                "type": "trade",
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "regime": regime,
                "source_engine": aggregated.get("source_engine"),
                "direction": signal,
                "result": result,
                "R_multiple": round(r_mult, 4),
                "pnl": round(pnl, 4),
                "duration_bars": exit_bar - i,
            }
        )
        i = exit_bar + 1

    return {
        "trades": trades,
        "decisions": decisions,
        "chronological": True,
        "shuffle": False,
    }


def run_walk_forward_router(
    candles: pd.DataFrame,
    *,
    config: RouterConfig,
    base_dir: str | None = None,
    dataset: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Expanding year windows 2021-2026; trend ML retrained on prior years only."""
    regime_frame = compute_regime_features_from_candles(candles)
    ts = regime_frame["timestamp"]
    windows_out: list[dict[str, Any]] = []

    range_engine = RangeEngineAdapter.load(symbol=config.symbol, base_dir=base_dir)

    for window in build_year_windows():
        year = window["test_year"]
        test_mask = _year_mask(ts, year)
        train_mask = _prior_years_mask(ts, year)
        if not test_mask.any():
            windows_out.append({**window, "skipped": True, "reason": "no_test_rows"})
            continue

        test_candles = _slice_candles_by_mask(candles, test_mask, regime_frame)
        if train_mask.any():
            train_candles = _slice_candles_by_mask(candles, train_mask, regime_frame)
            trend_engine = TrendEngineAdapter.load(
                train_candles,
                symbol=config.symbol,
                base_dir=base_dir,
                seed=config.seed,
                threshold=config.trend_ml_threshold,
            )
        else:
            trend_engine = TrendEngineAdapter.load(
                candles,
                symbol=config.symbol,
                base_dir=base_dir,
                seed=config.seed,
                threshold=config.trend_ml_threshold,
            )

        bt = run_router_backtest(
            test_candles,
            config=config,
            base_dir=base_dir,
            range_adapter=range_engine,
            trend_adapter=trend_engine,
            dataset=dataset,
        )
        from tradingbot.ml.research.regime_router.regime_performance import compute_regime_performance

        perf = compute_regime_performance(bt["trades"])
        windows_out.append(
            {
                **window,
                "test_rows": int(test_mask.sum()),
                "train_rows": int(train_mask.sum()),
                "metrics": perf["combined"],
                "regime_performance": perf,
                "trades": perf["combined"]["trades"],
                "shuffle": False,
            }
        )

    return {
        "phase": "13.5",
        "windows": windows_out,
        "chronological": True,
        "expanding": True,
        "shuffle": False,
    }


def _slice_candles_by_mask(candles: pd.DataFrame, mask: np.ndarray, regime_frame: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(regime_frame.loc[mask, "timestamp"], utc=True)
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
        elif "time" in c.columns:
            c = c.set_index("time")
    c.index = pd.to_datetime(c.index, utc=True)
    sliced = c.loc[c.index.isin(ts)]
    return sliced.sort_index()


def _merge_range_features(merged: pd.DataFrame, dataset: pd.DataFrame | None) -> pd.DataFrame:
    if dataset is None or dataset.empty:
        return merged
    cols = ["ema50_slope", "candle_direction", "structure_distance"]
    available = [c for c in cols if c in dataset.columns]
    if not available:
        return merged
    feat = dataset[["timestamp", *available]].copy()
    feat["timestamp"] = pd.to_datetime(feat["timestamp"], utc=True)
    out = merged.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out.merge(feat, on="timestamp", how="left")


def _candle_index_map(candles: pd.DataFrame) -> dict[pd.Timestamp, int]:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
        elif "time" in c.columns:
            c = c.set_index("time")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    return {pd.Timestamp(ts): i for i, ts in enumerate(c.index)}
