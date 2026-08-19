"""Phase 15G — RiskGate threshold simulation (read-only, no production changes)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_4.pipeline_simulator import simulate_trade_outcome
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy
from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter, ResearchCalibrationPolicy
from tradingbot.ml.research.phase14_7.quality_adapter import build_quality_adapter
from tradingbot.ml.research.phase14_7.risk_adapter import build_risk_adapter
from tradingbot.ml.research.phase15g.config import SIMULATION_THRESHOLDS
from tradingbot.ml.risk_intelligence.confidence_risk_mapper import confidence_risk_multiplier  # noqa: F401 — documented gate reference


def _simulate_threshold(
    unified: pd.DataFrame,
    candles: pd.DataFrame,
    adapter: Any,
    range_inner: Any,
    trend_inner: Any,
    *,
    symbol: str,
    timeframe: str,
    risk_confidence_threshold: float,
    cal_threshold: float,
    stride: int,
) -> dict[str, Any]:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    wins = 0
    losses = 0
    r_multiples: list[float] = []
    accepted = 0
    equity = 100.0
    peak = 100.0
    max_dd = 0.0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        cal, _, _ = adapter.evaluate(ctx)

        engine_sig = str(cal.raw_confidence.engine_signal)
        cal_conf = float(cal.final_confidence)

        sim_risk_allowed = cal_conf >= risk_confidence_threshold

        if (
            engine_sig not in ("BUY", "SELL")
            or cal_conf < cal_threshold
            or not sim_risk_allowed
        ):
            continue

        accepted += 1
        ts = pd.to_datetime(row["timestamp"], utc=True)
        bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
        outcome = simulate_trade_outcome(c, bar_idx, direction=engine_sig)
        r = float(outcome["r_multiple"])
        r_multiples.append(r)
        if r > 0:
            wins += 1
        elif r < 0:
            losses += 1
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    gross_profit = sum(r for r in r_multiples if r > 0)
    gross_loss = abs(sum(r for r in r_multiples if r < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    expectancy = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0
    win_rate = wins / accepted if accepted else 0.0

    return {
        "risk_confidence_threshold": risk_confidence_threshold,
        "calibration_threshold": cal_threshold,
        "accepted_trades": accepted,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 4) if pf != float("inf") else None,
        "expectancy": round(expectancy, 4),
        "max_drawdown": round(max_dd, 4),
        "simulated_risk_gate_only": True,
    }


def simulate_risk_gate_thresholds(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
    stride: int = 5,
    thresholds: tuple[float, ...] = SIMULATION_THRESHOLDS,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_inner = getattr(registry.get("phase9_9"), "inner", None)
    trend_inner = getattr(registry.get("trend_rf_v40"), "inner", None)

    policy = load_phase14_6_policy(base_dir)
    cal_threshold = float(policy.get("confidence_threshold", 0.30))
    method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=range_inner, trend_engine=trend_inner,
    )
    cal_adapter = ResearchCalibratedAdapter(
        DecisionOrchestrator(),
        calibration_method=method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=cal_threshold),
    )
    adapter = build_quality_adapter(build_risk_adapter(cal_adapter))

    results: list[dict[str, Any]] = []
    for th in thresholds:
        results.append(
            _simulate_threshold(
                unified, window, adapter, range_inner, trend_inner,
                symbol=symbol, timeframe=timeframe,
                risk_confidence_threshold=th,
                cal_threshold=cal_threshold,
                stride=stride,
            )
        )

    return {
        "phase": "15G",
        "simulation_only": True,
        "production_unchanged": True,
        "frozen_bundle": True,
        "calibration_threshold": cal_threshold,
        "thresholds_tested": list(thresholds),
        "results": results,
        "first_accepting_threshold": next(
            (r["risk_confidence_threshold"] for r in results if r["accepted_trades"] > 0),
            None,
        ),
    }
