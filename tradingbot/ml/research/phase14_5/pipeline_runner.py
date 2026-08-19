"""Phase 14.5 — pipeline runner with regime-adaptive confidence (read-only on 14.x)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase14_4.pipeline_simulator import (
    PipelineThresholds,
    build_quality_adapter,
    simulate_trade_outcome,
    trade_metrics_from_records,
)
from tradingbot.ml.research.phase14_5.config import DEFAULT_MAX_RISK_PERCENT, DEFAULT_QUALITY_THRESHOLD
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

BLOCKED_REGIMES = frozenset({"HIGH_VOLATILITY", "NO_TRADE"})


@dataclass
class RegimeConfidencePolicy:
    """Per-regime calibrated confidence floors."""

    thresholds: dict[str, float] = field(
        default_factory=lambda: {
            "RANGE": 0.55,
            "TREND": 0.55,
            "HIGH_VOLATILITY": 1.0,
            "NO_TRADE": 1.0,
        }
    )

    def threshold_for(self, regime: str) -> float:
        return float(self.thresholds.get(str(regime).upper(), 0.55))

    def passes(self, confidence: float, regime: str) -> bool:
        regime = str(regime).upper()
        if regime in BLOCKED_REGIMES:
            return False
        th = self.threshold_for(regime)
        if th >= 1.0:
            return False
        return float(confidence) >= th


def run_pipeline_with_policy(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    confidence_threshold: float | None = None,
    regime_policy: RegimeConfidencePolicy | None = None,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    max_risk_percent: float = DEFAULT_MAX_RISK_PERCENT,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 1,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    th = PipelineThresholds(
        confidence_threshold=confidence_threshold or 0.55,
        quality_threshold=quality_threshold,
        max_risk_percent=max_risk_percent,
    )
    adapter, range_engine, trend_engine = build_quality_adapter(
        candles,
        symbol=symbol,
        seed=seed,
        thresholds=th,
        range_engine=range_engine,
        trend_engine=trend_engine,
    )
    if unified is None:
        unified = build_unified_frame(candles, dataset)

    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    policy = regime_policy
    records: list[dict[str, Any]] = []

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
        regime = str(calibrated.decision.regime)
        conf = float(calibrated.final_confidence)

        if policy is not None:
            conf_ok = policy.passes(conf, regime)
            conf_threshold_used = policy.threshold_for(regime)
        else:
            conf_threshold_used = th.confidence_threshold
            conf_ok = conf >= conf_threshold_used and regime not in BLOCKED_REGIMES

        risk_allowed = risk.allowed and risk.risk_percent > 0 and risk.risk_percent <= max_risk_percent
        quality_allowed = quality.allowed
        final_allowed = (
            raw_signal in ("BUY", "SELL") and conf_ok and risk_allowed and quality_allowed
        )

        ts = pd.to_datetime(row["timestamp"], utc=True)
        bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
        outcome = (
            simulate_trade_outcome(c, bar_idx, direction=raw_signal)
            if raw_signal in ("BUY", "SELL")
            else {"r_multiple": 0.0, "mfe": 0.0, "mae": 0.0}
        )

        block_reason = None
        if not final_allowed:
            if raw_signal not in ("BUY", "SELL"):
                block_reason = "hold_action"
            elif not conf_ok:
                block_reason = "confidence"
            elif not risk_allowed:
                block_reason = "risk"
            elif not quality_allowed:
                block_reason = "quality"

        records.append(
            {
                "timestamp": str(ts),
                "year": int(ts.year),
                "raw_signal": raw_signal,
                "confidence": conf,
                "confidence_threshold_used": conf_threshold_used,
                "risk_percent": risk.risk_percent,
                "quality_score": quality.score,
                "allowed": final_allowed,
                "block_reason": block_reason,
                "engine": calibrated.decision.engine,
                "regime": regime,
                "r_multiple": outcome["r_multiple"],
                "mfe": outcome["mfe"],
                "mae": outcome["mae"],
                "decision_reason": calibrated.decision.explanation,
            }
        )
    return records


def sweep_metrics(records: list[dict[str, Any]], *, stride: int = 1) -> dict[str, Any]:
    base = trade_metrics_from_records(records)
    signals = [r for r in records if r["raw_signal"] in ("BUY", "SELL")]
    blocked = [r for r in signals if not r["allowed"]]
    accepted = [r for r in records if r["allowed"]]

    missed_winners = sum(1 for r in blocked if float(r["r_multiple"]) > 0.5)
    false_acceptance = sum(1 for r in accepted if float(r["r_multiple"]) < 0)
    profitable_raw = sum(1 for r in signals if float(r["r_multiple"]) > 0)
    profitable_accepted = sum(1 for r in accepted if float(r["r_multiple"]) > 0)

    precision = profitable_accepted / len(accepted) if accepted else 0.0
    recall = profitable_accepted / profitable_raw if profitable_raw else 0.0

    return {
        **base,
        "effective_trades_est": int(base["trades"] * max(1, stride)),
        "total_signals": len(signals),
        "accepted_trades": len(accepted),
        "rejected_trades": len(blocked),
        "missed_winners": missed_winners,
        "false_acceptance": false_acceptance,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }
