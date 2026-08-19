"""Phase 19B — enriched trade dataset from production pipeline (research only)."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase19a.backtest import _duration_bars
from tradingbot.ml.phase19a.config import DEFAULT_STRIDE, DEFAULT_WARMUP
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.trade_tracker import simulate_outcome
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.phase19b.config import BACKTEST_DAYS
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

FEATURE_KEYS = (
    "adx", "atr", "rsi", "spread", "trend_age", "ema_curvature",
    "adx_acceleration", "swing_efficiency", "atr_percentile",
)


def _feat(row: pd.Series, key: str, default: float = 0.0) -> float:
    if key in row.index:
        try:
            return float(row[key])
        except (TypeError, ValueError):
            return default
    return default


def _session(hour: int) -> str:
    if 0 <= hour < 8:
        return "ASIA"
    if 8 <= hour < 13:
        return "LONDON"
    if 13 <= hour < 21:
        return "NY"
    return "LATE"


def collect_enriched_trades(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = BACKTEST_DAYS,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP,
) -> list[dict[str, Any]]:
    """Replay production path with TREND=v41; attach features for research analysis."""
    window = prepare_calibration_candles(candles, days=days)
    unified = attach_top5_features(build_unified_frame(window, dataset))

    c = window.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    PipelineCache.reset()
    try:
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
        range_inner, trend_inner = adapter._engine_inners()  # noqa: SLF001

        records: list[dict[str, Any]] = []
        start = max(warmup, 0)
        for i in range(start, len(unified), max(1, stride)):
            row = unified.iloc[i]
            regime = rule_classify_row(row)
            ctx = build_market_context(
                row, symbol=symbol, timeframe=timeframe,
                range_engine=range_inner, trend_engine=trend_inner,
            )
            calibrated, risk, quality = stack.quality.evaluate(ctx)
            action = str(calibrated.final_action)
            if action not in ("BUY", "SELL"):
                action = "HOLD"
            allowed = action in ("BUY", "SELL") and risk.allowed and quality.allowed
            if not allowed:
                continue

            ts = pd.to_datetime(row.get("timestamp", row.name), utc=True)
            bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
            outcome = simulate_outcome(c, bar_idx, action)
            duration = _duration_bars(c, bar_idx, action)
            entry = float(c.iloc[bar_idx]["close"])
            atr = float(c.iloc[bar_idx]["high"] - c.iloc[bar_idx]["low"])
            sl_dist = max(atr, entry * 0.0005)

            rec: dict[str, Any] = {
                "timestamp": ts.isoformat(),
                "year": int(ts.year),
                "month": int(ts.month),
                "weekday": int(ts.weekday()),
                "hour": int(ts.hour),
                "session": _session(int(ts.hour)),
                "regime": regime,
                "engine": calibrated.decision.engine,
                "direction": action,
                "allowed": True,
                "confidence": float(calibrated.final_confidence),
                "risk_percent": float(risk.risk_percent),
                "quality_score": float(quality.score),
                "r_multiple": float(outcome["r_multiple"]),
                "mfe": float(outcome["mfe"]),
                "mae": float(outcome["mae"]),
                "duration_bars": duration,
                "sl_distance": round(sl_dist, 6),
                "tp_distance": round(sl_dist * 2.0, 6),
                "is_win": float(outcome["r_multiple"]) > 0,
                "is_loss": float(outcome["r_multiple"]) < 0,
            }
            for k in FEATURE_KEYS:
                rec[k] = _feat(row, k)
            if rec["spread"] == 0.0 and "spread" not in row.index:
                rec["spread"] = atr * 0.01  # proxy when spread column absent
            records.append(rec)
        return records
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev
