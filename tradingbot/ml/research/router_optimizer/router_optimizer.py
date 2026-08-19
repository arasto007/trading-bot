"""Phase 13.6 — tunable regime router backtest engine (research only)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.paper_trading.signal_engine import SignalConfig, SignalEngine
from tradingbot.ml.research.phase11_5._metrics import trade_metrics
from tradingbot.ml.research.regime_detector.regime_features import compute_regime_features_from_candles
from tradingbot.ml.research.regime_router.config import MAX_HOLD_BARS
from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
from tradingbot.ml.research.regime_router.signal_aggregator import aggregate_signal
from tradingbot.ml.research.regime_router.trend_engine_adapter import TrendEngineAdapter
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import (
    OptimizerConfig,
    RegimeThresholdParams,
    baseline_phase135_config,
    classify_regime_row,
    classify_regimes,
    composite_score,
    config_to_dict,
)
from tradingbot.ml.research.router_optimizer.trade_filter_optimizer import resolve_routing_action
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features

__all__ = [
    "OptimizerConfig",
    "RegimeThresholdParams",
    "baseline_phase135_config",
    "classify_regime_row",
    "classify_regimes",
    "composite_score",
    "prepare_merged_frame",
    "run_optimized_backtest",
]


def prepare_merged_frame(candles: pd.DataFrame, dataset: pd.DataFrame | None) -> pd.DataFrame:
    regime_frame = compute_regime_features_from_candles(candles)
    trend_frame = build_ml_features(candles)
    merged = trend_frame.merge(regime_frame, on="timestamp", how="left", suffixes=("", "_reg"))
    if dataset is not None and not dataset.empty:
        cols = ["ema50_slope", "candle_direction", "structure_distance"]
        available = [c for c in cols if c in dataset.columns]
        if available:
            feat = dataset[["timestamp", *available]].copy()
            feat["timestamp"] = pd.to_datetime(feat["timestamp"], utc=True)
            merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)
            # Dataset Phase 9.9 features override trend_ml homonyms (e.g. ema50_slope).
            drop_cols = [c for c in available if c in merged.columns]
            if drop_cols:
                merged = merged.drop(columns=drop_cols)
            merged = merged.merge(feat, on="timestamp", how="left")
            for col in available:
                if col in merged.columns:
                    merged[col] = merged[col].fillna(0.0)
    return merged.sort_values("timestamp").reset_index(drop=True)


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
    exit_price = entry
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


def run_optimized_backtest(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    config: OptimizerConfig,
    range_adapter: RangeEngineAdapter | None = None,
    trend_adapter: TrendEngineAdapter | None = None,
    engine_cache: EngineCache | None = None,
    base_dir: str | None = None,
    initial_equity: float = 10_000.0,
    session_filter: Callable[[pd.Timestamp], bool] | None = None,
) -> dict[str, Any]:
    """Chronological router simulation with tunable thresholds and policies."""
    range_engine = range_adapter or (engine_cache.range_engine() if engine_cache else RangeEngineAdapter.load(symbol=config.symbol, base_dir=base_dir))
    range_engine.signal_engine = SignalEngine(
        SignalConfig(
            buy_threshold=config.range_buy_threshold,
            sell_threshold=config.range_sell_threshold,
        )
    )
    if trend_adapter is not None:
        trend_engine = trend_adapter
    elif engine_cache is not None:
        trend_engine = engine_cache.trend_engine(config.trend_ml_threshold)
    else:
        trend_engine = TrendEngineAdapter.load(
            candles,
            symbol=config.symbol,
            base_dir=base_dir,
            seed=config.seed,
            threshold=config.trend_ml_threshold,
        )
    trend_engine.threshold = config.trend_ml_threshold

    regimes = classify_regimes(merged, config.regime_params)
    trades: list[dict[str, Any]] = []
    equity = initial_equity
    candle_index_map = _candle_index_map(candles)
    i = 0
    n = len(merged)

    while i < n - 1:
        row = merged.iloc[i]
        regime = str(regimes.iloc[i])
        ts = pd.Timestamp(row["timestamp"])
        action = resolve_routing_action(regime, config.policy)

        range_out = trend_out = None
        if action == "RANGE":
            bar_index = candle_index_map.get(ts)
            if bar_index is not None:
                range_out = range_engine.evaluate(row=row, candles=candles, bar_index=bar_index)
        elif action == "TREND":
            trend_out = trend_engine.evaluate(row, regime="TREND")
        elif action == "BLOCK":
            trades.append(
                {
                    "type": "block",
                    "timestamp": ts.isoformat(),
                    "regime": regime,
                    "policy": config.policy,
                }
            )

        routed = {
            "action": action if action != "BLOCK" else "BLOCK",
            "regime": regime,
            "source_engine": (range_out or trend_out or {}).get("engine"),
            "signal": "HOLD",
            "engine_output": range_out or trend_out,
            "reason": f"policy_{config.policy}" if action == "BLOCK" else None,
        }
        if action == "BLOCK":
            routed["reason"] = routed.get("reason") or f"regime_{regime.lower()}"
        elif action == "RANGE" and range_out:
            routed["signal"] = range_out.get("signal", "HOLD")
        elif action == "TREND" and trend_out:
            routed["signal"] = trend_out.get("signal", "HOLD")

        aggregated = aggregate_signal(routed)
        confidence = float(aggregated.get("confidence", 0.0))
        if config.min_confidence > 0 and aggregated["final_signal"] in ("BUY", "SELL"):
            if confidence < config.min_confidence:
                i += 1
                continue
        if session_filter is not None and aggregated["final_signal"] in ("BUY", "SELL"):
            if not session_filter(ts):
                i += 1
                continue

        signal = aggregated["final_signal"]
        if signal not in ("BUY", "SELL"):
            i += 1
            continue

        risk = aggregated["risk_parameters"]
        entry = float(risk.get("entry") or row["close"])
        sl = float(risk["sl"])
        tp = float(risk["tp"])
        risk_amount = equity * float(risk.get("risk_pct", 0.005))
        result, exit_price, r_mult, exit_bar = _simulate_trade(
            merged, i, direction=signal, entry=entry, sl=sl, tp=tp
        )
        pnl = r_mult * risk_amount
        equity += pnl
        trades.append(
            {
                "type": "trade",
                "timestamp": ts.isoformat(),
                "regime": regime,
                "policy": config.policy,
                "source_engine": aggregated.get("source_engine"),
                "direction": signal,
                "confidence": confidence,
                "probability": aggregated.get("probability"),
                "result": result,
                "R_multiple": round(r_mult, 4),
                "pnl": round(pnl, 4),
                "duration_bars": exit_bar - i,
                "adx": float(row.get("adx", 0.0)),
                "atr_percentile": float(row.get("atr_percentile", 0.0)),
            }
        )
        i = exit_bar + 1

    executed = [t for t in trades if t.get("type") == "trade"]
    metrics = trade_metrics(executed, initial_equity=initial_equity)
    metrics["expectancy"] = metrics.pop("expectancy_r")
    return {
        "trades": trades,
        "metrics": metrics,
        "config": config_to_dict(config),
        "chronological": True,
        "shuffle": False,
    }
