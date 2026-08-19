"""Phase 14.1 — validation helpers and context building for tests/CLI."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import phase9_9_model_path, reports_dir
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.confidence_engine import compute_regime_strength
from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID, TREND_ML_THRESHOLD
from tradingbot.ml.decision_engine.decision_types import EngineSignal, MarketContext
from tradingbot.ml.decision_engine.strategy_selector import BLOCKED_REGIMES, select_engine
from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
from tradingbot.ml.research.phase13_8.trend_label_v2 import build_labeled_samples
from tradingbot.ml.research.phase13_8.trend_ml_retrainer import fit_production_model
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import UnifiedRangeWrapper
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"


def phase14_1_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase14_1"


def phase14_1_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_1_reports_dir(base_dir) / "phase14_1_final_report.json"


def _infer_session(ts: datetime) -> str:
    hour = ts.hour
    if hour < 6:
        return "rollover"
    if hour < 12:
        return "london"
    if hour < 17:
        return "new_york"
    return "off_hours"


def _engine_signal_from_eval(ev: dict[str, Any], *, model: str) -> EngineSignal:
    sig = str(ev.get("signal", "HOLD"))
    if sig not in ("BUY", "SELL", "HOLD"):
        sig = "HOLD"
    return EngineSignal(
        signal=sig,  # type: ignore[arg-type]
        confidence=float(ev.get("confidence", 0.0)),
        model=model,
        probability=float(ev.get("probability", 0.0)),
        metadata={
            "engine": ev.get("engine"),
            "model_version": ev.get("model_version"),
            "allow_trade": ev.get("allow_trade"),
        },
    )


def load_production_engines(
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    seed: int = 42,
) -> tuple[UnifiedRangeWrapper, RecoveredTrendEngine]:
    """Load frozen Phase 9.9 range + Phase 13.10 validated trend (read-only artifacts)."""
    range_inner = RangeEngineAdapter.load(symbol=symbol)
    range_engine = UnifiedRangeWrapper(range_inner)

    frame = build_ml_features(candles)
    samples = build_labeled_samples(
        frame, symbol=symbol, rule_fn=evaluate_variant_a, label_key="label_a_tp_before_sl"
    )
    model_name = "random_forest"
    if samples.empty:
        raise ValueError("Insufficient labeled samples to fit production trend model")
    model, scaler, _ = fit_production_model(samples, model_name=model_name, seed=seed)
    trend_engine = RecoveredTrendEngine(
        model=model,
        scaler=scaler,
        model_name=model_name,
        threshold=TREND_ML_THRESHOLD,
        rule_fn=evaluate_variant_a,
        symbol=symbol,
    )
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    trend_engine.model_version = resolve_active_trend_engine_id()
    return range_engine, trend_engine


def build_market_context(
    row: pd.Series,
    *,
    symbol: str,
    timeframe: str,
    range_engine: UnifiedRangeWrapper,
    trend_engine: RecoveredTrendEngine,
    timestamp: datetime | None = None,
    candles: pd.DataFrame | None = None,
    bar_index: int | None = None,
) -> MarketContext:
    features = row.to_dict()
    regime = rule_classify_row(row)
    ts = timestamp
    if ts is None and "timestamp" in features:
        ts = pd.to_datetime(features["timestamp"], utc=True).to_pydatetime()
    if ts is None:
        ts = datetime.now(timezone.utc)

    range_ev = range_engine.evaluate(
        row=row,
        candles=candles,
        bar_index=bar_index,
        timeframe=timeframe,
    )
    trend_ev = trend_engine.evaluate(row, regime=regime)
    vol = float(features.get("atr_percentile", features.get("volatility", 50.0)))

    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    return MarketContext(
        symbol=symbol,
        timeframe=timeframe,
        features=features,
        regime=regime,
        regime_strength=compute_regime_strength(features, regime),
        range_signal=_engine_signal_from_eval(range_ev, model=RANGE_MODEL_ID),
        trend_signal=_engine_signal_from_eval(trend_ev, model=resolve_active_trend_engine_id()),
        volatility=vol,
        session=_infer_session(ts),
        timestamp=ts,
    )


def validate_routing_table() -> dict[str, str | None]:
    return {
        "RANGE": select_engine("RANGE"),
        "TREND": select_engine("TREND"),
        "HIGH_VOLATILITY": select_engine("HIGH_VOLATILITY"),
        "NO_TRADE": select_engine("NO_TRADE"),
    }


def validate_routing() -> dict[str, Any]:
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    table = validate_routing_table()
    active_trend = resolve_active_trend_engine_id()
    ok = (
        table["RANGE"] == RANGE_MODEL_ID
        and table["TREND"] == active_trend
        and table["HIGH_VOLATILITY"] is None
        and table["NO_TRADE"] is None
    )
    return {"routing_table": table, "passes": ok}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_artifacts_unchanged() -> dict[str, Any]:
    path = phase9_9_model_path(None)
    checksum = sha256_file(path)
    return {"phase9_9_model_path": str(path), "checksum": checksum, "exists": path.is_file()}


def run_decision_batch(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 30,
    seed: int = 42,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    from tradingbot.ml.decision_engine.decision_trace import summarize_decisions, trace_record, write_decision_metrics
    from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator

    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw)
    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")

    if not isinstance(candles.index, pd.DatetimeIndex):
        candles = candles.copy()
        if "timestamp" in candles.columns:
            candles = candles.set_index("timestamp")
    candles.index = pd.to_datetime(candles.index, utc=True)
    cutoff = candles.index.max() - pd.Timedelta(days=days)
    candles = candles.loc[candles.index >= cutoff]

    unified = build_unified_frame(candles, raw)
    range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)
    orchestrator = DecisionOrchestrator(persist_traces=False)

    records: list[dict[str, Any]] = []
    routing_counts = {"RANGE": 0, "TREND": 0, "HIGH_VOLATILITY": 0, "NO_TRADE": 0}
    engine_counts: dict[str, int] = {}
    action_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}

    for i in range(len(unified)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        routing_counts[ctx.regime] = routing_counts.get(ctx.regime, 0) + 1
        decision = orchestrator.decide(ctx)
        action_counts[decision.action] = action_counts.get(decision.action, 0) + 1
        if decision.engine:
            engine_counts[decision.engine] = engine_counts.get(decision.engine, 0) + 1
        records.append(trace_record(decision, ctx))

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)

    metrics = summarize_decisions(records)
    metrics["routing_counts"] = routing_counts
    metrics["blocked_regimes"] = {r: routing_counts.get(r, 0) for r in BLOCKED_REGIMES}

    write_decision_metrics(metrics, base_dir=base_dir)

    routing_validation = validate_routing()
    artifact_validation = validate_artifacts_unchanged()

    return {
        "records": records,
        "metrics": metrics,
        "routing_validation": routing_validation,
        "artifact_validation": artifact_validation,
        "fingerprint_before": fp_before,
        "fingerprint_after": fp_after,
        "fingerprint_unchanged": fp_before == fp_after,
        "bars_processed": len(unified),
        "days": days,
    }
