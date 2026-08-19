"""Phase 15F — reconnect Phase 14.6 Platt calibration to production integration."""

from __future__ import annotations

import threading
from typing import Any

import pandas as pd

from tradingbot.ml.confidence_engine.validator import CalibratedDecisionAdapter
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.research.phase14_6.research_calibrator import (
    ResearchCalibratedAdapter,
    ResearchCalibrationPolicy,
)
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_7.config import MAX_RESEARCH_BARS, load_phase14_6_policy

_lock = threading.Lock()
_cached: dict[str, Any] = {}


def prepare_calibration_candles(candles: pd.DataFrame, *, days: int = 180) -> pd.DataFrame:
    """Match Phase 14.7 research window — recent days, capped at MAX_RESEARCH_BARS."""
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    cutoff = c.index.max() - pd.Timedelta(days=days)
    c = c.loc[c.index >= cutoff].sort_index()
    if len(c) > MAX_RESEARCH_BARS:
        c = c.iloc[:: max(1, len(c) // MAX_RESEARCH_BARS)]
    return c


def build_production_calibrated_adapter(
    orchestrator: DecisionOrchestrator,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
) -> CalibratedDecisionAdapter | ResearchCalibratedAdapter:
    """
    Production calibration bridge — restores Phase 14.6 Platt path validated in Phase 14.7.

    Returns ResearchCalibratedAdapter (same decide() contract as CalibratedDecisionAdapter).
    """
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    cache_key = f"{base_dir}:{symbol}:{timeframe}:{seed}:{resolve_active_trend_engine_id()}"
    with _lock:
        if cache_key in _cached:
            method, policy_cfg = _cached[cache_key]
        else:
            from tradingbot.ml.data.stores.candle_store import CandleStore
            from tradingbot.ml.dataset.store import DatasetStore

            candles = CandleStore(base_dir).load(symbol, timeframe)
            dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
            if candles is None or candles.empty or dataset is None or dataset.empty:
                return CalibratedDecisionAdapter(orchestrator)

            fit_candles = prepare_calibration_candles(candles, days=180)
            from tradingbot.ml.phase15a.engine_registry import EngineRegistry

            active_trend_id = resolve_active_trend_engine_id()
            eng_registry = EngineRegistry.build_default(
                base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
            )
            range_wrapped = eng_registry.get("phase9_9")
            trend_wrapped = eng_registry.get(active_trend_id)
            range_inner = getattr(range_wrapped, "inner", None) if range_wrapped else None
            trend_inner = getattr(trend_wrapped, "inner", None) if trend_wrapped else None
            if trend_inner is None:
                return CalibratedDecisionAdapter(orchestrator)

            from tradingbot.ml.phase15a.config import TREND_ENGINE_V41_ID
            from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

            unified = build_unified_frame(fit_candles, dataset)
            if active_trend_id == TREND_ENGINE_V41_ID:
                from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
                from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

                if "regime" not in unified.columns:
                    unified = unified.copy()
                    unified["regime"] = [rule_classify_row(unified.iloc[i]) for i in range(len(unified))]
                unified = attach_top5_features(unified)

            method, policy_cfg = load_recovered_calibration(
                fit_candles,
                dataset,
                base_dir=base_dir,
                symbol=symbol,
                timeframe=timeframe,
                seed=seed,
                stride=5,
                range_engine=range_inner,
                trend_engine=trend_inner,
                unified=unified,
            )
            _cached[cache_key] = (method, policy_cfg)

    threshold = float(policy_cfg.get("confidence_threshold", 0.30))
    from tradingbot.ml.research.phase22c.config import load_phase22c_config

    cfg22 = load_phase22c_config()
    if cfg22.enabled:
        threshold = min(threshold, cfg22.calibration_min_confidence)
    return ResearchCalibratedAdapter(
        orchestrator,
        calibration_method=method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=threshold),
    )


def calibration_status(base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    policy = load_phase14_6_policy(base_dir)
    active_trend_id = resolve_active_trend_engine_id()
    return {
        "production_uses_platt": True,
        "active_trend_engine_id": active_trend_id,
        "calibration_method": policy.get("calibration_method", "platt"),
        "confidence_threshold": policy.get("confidence_threshold", 0.30),
        "phase14_6_policy": policy,
        "platt_fit_window": "phase14_7 MAX_RESEARCH_BARS on active EngineRegistry trend engine",
        "missing_in_prior_production": "Platt calibration from Phase 14.6 was not wired in factory.py",
        "prior_path": "CalibratedDecisionAdapter + ConfidenceCalibrator (heuristic 14.2A)",
        "recovered_path": "ResearchCalibratedAdapter + Phase 14.6 Platt",
    }
