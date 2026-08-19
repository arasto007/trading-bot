"""Phase 14.4 — pipeline simulation with injectable thresholds (read-only on 14.x core)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.confidence_engine.calibration_policy import CalibrationPolicy
from tradingbot.ml.confidence_engine.validator import CalibratedDecisionAdapter
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase14_4.config import DEFAULT_RR, MAX_HOLD_BARS
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
from tradingbot.ml.risk_intelligence.risk_policy import RiskPolicy
from tradingbot.ml.risk_intelligence.risk_types import AccountState, HistoricalMetrics
from tradingbot.ml.risk_intelligence.validator import AdaptiveRiskAdapter
from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_policy import QualityPolicy


@dataclass(frozen=True)
class PipelineThresholds:
    confidence_threshold: float = 0.55
    quality_threshold: float = 0.65
    max_risk_percent: float = 0.50


def build_quality_adapter(
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    seed: int = 42,
    thresholds: PipelineThresholds | None = None,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
) -> tuple[TradeQualityAdapter, Any, Any]:
    th = thresholds or PipelineThresholds()
    if range_engine is None or trend_engine is None:
        range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)
    orchestrator = DecisionOrchestrator()
    cal_policy = CalibrationPolicy(min_calibrated_confidence=th.confidence_threshold)
    decision_adapter = CalibratedDecisionAdapter(orchestrator, policy=cal_policy)
    account = AccountState()
    history = HistoricalMetrics(engine_trade_count={"phase9_9": 3788, "trend_rf_v40": 1205})
    risk_engine = AdaptiveRiskEngine(policy=RiskPolicy(max_risk_percent=th.max_risk_percent))
    risk_adapter = AdaptiveRiskAdapter(
        decision_adapter,
        risk_engine=risk_engine,
        account=account,
        history=history,
    )
    quality_engine = TradeQualityEngine(
        policy=QualityPolicy(threshold=th.quality_threshold),
        history=history,
    )
    adapter = TradeQualityAdapter(risk_adapter, quality_engine=quality_engine)
    return adapter, range_engine, trend_engine


def _prepare_candles(candles: pd.DataFrame) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    return c.sort_index()


def simulate_trade_outcome(
    candles: pd.DataFrame,
    bar_index: int,
    *,
    direction: str,
    rr: float = DEFAULT_RR,
) -> dict[str, float]:
    """Forward simulation for research metrics (MFE/MAE/R)."""
    c = _prepare_candles(candles)
    if bar_index >= len(c) - 1:
        return {"r_multiple": 0.0, "mfe": 0.0, "mae": 0.0}

    entry = float(c.iloc[bar_index]["close"])
    atr = float(c.iloc[bar_index].get("high", entry) - c.iloc[bar_index].get("low", entry))
    sl_dist = max(atr, entry * 0.0005)
    if direction == "BUY":
        sl, tp = entry - sl_dist, entry + sl_dist * rr
    else:
        sl, tp = entry + sl_dist, entry - sl_dist * rr

    mfe = 0.0
    mae = 0.0
    r_unit = abs(entry - sl)
    end = min(bar_index + MAX_HOLD_BARS, len(c) - 1)
    exit_r = 0.0

    for j in range(bar_index + 1, end + 1):
        bar = c.iloc[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        if direction == "BUY":
            fav = (hi - entry) / r_unit if r_unit > 0 else 0.0
            adv = (entry - lo) / r_unit if r_unit > 0 else 0.0
            mfe = max(mfe, fav)
            mae = max(mae, adv)
            if lo <= sl:
                exit_r = -1.0
                break
            if hi >= tp:
                exit_r = rr
                break
        else:
            fav = (entry - lo) / r_unit if r_unit > 0 else 0.0
            adv = (hi - entry) / r_unit if r_unit > 0 else 0.0
            mfe = max(mfe, fav)
            mae = max(mae, adv)
            if hi >= sl:
                exit_r = -1.0
                break
            if lo <= tp:
                exit_r = rr
                break
    else:
        close = float(c.iloc[end]["close"])
        if direction == "BUY":
            exit_r = (close - entry) / r_unit if r_unit > 0 else 0.0
        else:
            exit_r = (entry - close) / r_unit if r_unit > 0 else 0.0

    return {"r_multiple": round(exit_r, 4), "mfe": round(mfe, 4), "mae": round(mae, 4)}


def run_pipeline_records(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    thresholds: PipelineThresholds | None = None,
    adapter: TradeQualityAdapter | None = None,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    stride: int = 1,
) -> list[dict[str, Any]]:
    if adapter is None or range_engine is None or trend_engine is None:
        adapter, range_engine, trend_engine = build_quality_adapter(
            candles, symbol=symbol, seed=seed, thresholds=thresholds
        )
    if unified is None:
        unified = build_unified_frame(candles, dataset)
    c = _prepare_candles(candles)
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    records: list[dict[str, Any]] = []
    th = thresholds or PipelineThresholds()

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        calibrated, risk, quality = adapter.evaluate(ctx)
        raw_signal = str(calibrated.decision.metadata.get("raw_engine_signal", "HOLD"))

        risk_allowed = risk.allowed and risk.risk_percent > 0 and risk.risk_percent <= th.max_risk_percent
        quality_allowed = quality.allowed
        final_allowed = (
            raw_signal in ("BUY", "SELL")
            and calibrated.final_confidence >= th.confidence_threshold
            and risk_allowed
            and quality_allowed
        )

        ts = pd.to_datetime(row["timestamp"], utc=True)
        bar_idx = ts_to_idx.get(pd.Timestamp(ts), i)
        outcome = simulate_trade_outcome(c, bar_idx, direction=raw_signal) if raw_signal in ("BUY", "SELL") else {
            "r_multiple": 0.0,
            "mfe": 0.0,
            "mae": 0.0,
        }

        block_reason = None
        if not final_allowed:
            if raw_signal not in ("BUY", "SELL"):
                block_reason = "hold_action"
            elif calibrated.final_confidence < th.confidence_threshold:
                block_reason = "confidence"
            elif not risk_allowed:
                block_reason = "risk"
            elif not quality_allowed:
                block_reason = "quality"

        records.append(
            {
                "timestamp": str(ts),
                "raw_signal": raw_signal,
                "confidence": calibrated.final_confidence,
                "risk_percent": risk.risk_percent,
                "quality_score": quality.score,
                "allowed": final_allowed,
                "block_reason": block_reason,
                "engine": calibrated.decision.engine,
                "regime": calibrated.decision.regime,
                "r_multiple": outcome["r_multiple"],
                "mfe": outcome["mfe"],
                "mae": outcome["mae"],
                "decision_reason": calibrated.decision.explanation,
            }
        )
    return records


def trade_metrics_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in records if r["allowed"]]
    r_vals = [float(r["r_multiple"]) for r in accepted]
    trades = len(accepted)
    if not r_vals:
        return {
            "trades": 0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
        }
    wins = sum(x for x in r_vals if x > 0)
    losses = abs(sum(x for x in r_vals if x < 0))
    pf = wins / losses if losses > 0 else (2.0 if wins > 0 else 0.0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in r_vals:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": trades,
        "profit_factor": round(pf, 4),
        "expectancy": round(sum(r_vals) / len(r_vals), 4),
        "win_rate": round(sum(1 for x in r_vals if x > 0) / len(r_vals), 4),
        "max_drawdown": round(max_dd, 4),
    }
