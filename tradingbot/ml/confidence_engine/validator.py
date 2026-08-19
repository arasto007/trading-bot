"""Phase 14.2A — integration adapter and batch validation."""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import phase13_4_reports_dir, phase9_9_model_path, reports_dir
from tradingbot.ml.confidence_engine.calibration_policy import DEFAULT_CALIBRATION_POLICY, CalibrationPolicy
from tradingbot.ml.confidence_engine.calibration_trace import (
    append_calibration_event,
    build_calibration_trace,
    write_calibration_metrics,
)
from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
from tradingbot.ml.confidence_engine.calibrator import ConfidenceCalibrator
from tradingbot.ml.confidence_engine.volatility_adjuster import classify_volatility
from tradingbot.ml.decision_engine.confidence_engine import compute_market_quality
from tradingbot.ml.decision_engine.decision_types import FinalDecision, MarketContext
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"


def phase14_2a_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase14_2a"


def phase14_2a_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_2a_reports_dir(base_dir) / "final_report.json"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_confidence_from_decision(decision: FinalDecision, context: MarketContext) -> RawConfidence:
    meta = decision.metadata or {}
    model_prob = float(meta.get("probability", meta.get("model_confidence", 0.0)))
    engine_signal = str(meta.get("raw_engine_signal", "HOLD"))
    vol_state = classify_volatility(context.volatility)
    return RawConfidence(
        raw_value=float(decision.confidence),
        engine=decision.engine,
        regime=decision.regime,
        model_probability=model_prob,
        regime_strength=float(context.regime_strength),
        market_quality=compute_market_quality(context),
        session=context.session,
        volatility=float(context.volatility),
        volatility_state=vol_state,
        engine_signal=engine_signal,
    )


@dataclass
class CalibratedDecision:
    """Phase 14.1 decision enriched with calibration (adapter output)."""

    decision: FinalDecision
    raw_confidence: RawConfidence
    calibrated: Any
    final_action: str
    final_confidence: float
    calibration_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.final_action,
            "selected_engine": self.decision.engine,
            "regime": self.decision.regime,
            "raw_confidence": self.raw_confidence.to_dict(),
            "calibrated_confidence": self.calibrated.to_dict(),
            "confidence": round(self.final_confidence, 6),
            "timestamp": self.decision.timestamp.isoformat(),
            "reason": self.decision.explanation + self.calibrated.explanation,
            "trace": self.decision.trace + self.calibrated.trace,
            "calibration_trace": self.calibration_trace,
            "metadata": self.decision.metadata,
        }


class CalibratedDecisionAdapter:
    """
    Dependency-injection wrapper: Phase 14.1 orchestrator → calibration → policy gate.
    Does not modify Phase 14.1 orchestrator source.
    """

    def __init__(
        self,
        orchestrator: DecisionOrchestrator,
        *,
        calibrator: ConfidenceCalibrator | None = None,
        policy: CalibrationPolicy | None = None,
        persist_events: bool = False,
        base_dir: str | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.calibrator = calibrator or ConfidenceCalibrator()
        self.policy = policy or DEFAULT_CALIBRATION_POLICY
        self.persist_events = persist_events
        self.base_dir = base_dir

    def decide(self, context: MarketContext) -> CalibratedDecision:
        decision = self.orchestrator.decide(context)
        raw = raw_confidence_from_decision(decision, context)
        calibrated = self.calibrator.calibrate(raw)

        engine_signal = raw.engine_signal
        final_conf = calibrated.calibrated_value
        if self.policy.passes_gate(final_conf) and engine_signal in ("BUY", "SELL"):
            final_action = engine_signal
        else:
            final_action = "HOLD"

        cal_trace = build_calibration_trace(raw, calibrated, adjustment_lines=calibrated.adjustments)
        if self.persist_events:
            append_calibration_event(cal_trace, base_dir=self.base_dir)

        enriched = CalibratedDecision(
            decision=decision,
            raw_confidence=raw,
            calibrated=calibrated,
            final_action=final_action,
            final_confidence=final_conf,
            calibration_trace=cal_trace,
        )
        return enriched


def summarize_calibration_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    raw_vals = [float(r["raw_confidence"]["raw_value"]) for r in records]
    cal_vals = [float(r["calibrated_confidence"]["calibrated_value"]) for r in records]
    before_accepted = sum(1 for r in records if r.get("phase14_1_action") in ("BUY", "SELL"))
    after_accepted = sum(1 for r in records if r.get("action") in ("BUY", "SELL"))

    def _dist(values: list[float]) -> dict[str, float]:
        if not values:
            return {"mean": 0.0, "std": 0.0, "p50": 0.0}
        return {
            "mean": round(statistics.mean(values), 4),
            "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
            "p50": round(statistics.median(values), 4),
        }

    engine_contrib: dict[str, int] = {}
    for r in records:
        if r.get("action") in ("BUY", "SELL") and r.get("selected_engine"):
            eng = str(r["selected_engine"])
            engine_contrib[eng] = engine_contrib.get(eng, 0) + 1

    return {
        "bars": len(records),
        "mean_raw_confidence": _dist(raw_vals)["mean"],
        "mean_calibrated_confidence": _dist(cal_vals)["mean"],
        "raw_distribution": _dist(raw_vals),
        "calibrated_distribution": _dist(cal_vals),
        "phase14_1_accepted": before_accepted,
        "phase14_2a_accepted": after_accepted,
        "acceptance_rate_before": round(before_accepted / len(records), 4) if records else 0.0,
        "acceptance_rate_after": round(after_accepted / len(records), 4) if records else 0.0,
        "engine_contribution_after": engine_contrib,
        "calibration_stability": round(1.0 - _dist(cal_vals)["std"], 4) if cal_vals else 0.0,
    }


def run_calibration_batch(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 30,
    seed: int = 42,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.decision_engine.validation import (
        build_market_context,
        load_production_engines,
    )
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

    store = DatasetStore(base_dir)
    raw_ds = store.load_v2(symbol, timeframe)
    if raw_ds is None or raw_ds.empty:
        raise FileNotFoundError(f"Dataset not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw_ds)
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

    unified = build_unified_frame(candles, raw_ds)
    range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)
    orchestrator = DecisionOrchestrator()
    adapter = CalibratedDecisionAdapter(orchestrator, persist_events=False, base_dir=str(base_dir) if base_dir else None)

    records: list[dict[str, Any]] = []
    calibration_events: list[dict[str, Any]] = []
    engine_stats: dict[str, list[float]] = {}
    regime_stats: dict[str, list[float]] = {}

    for i in range(len(unified)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        enriched = adapter.decide(ctx)
        calibration_events.append(enriched.calibration_trace)
        payload = enriched.to_dict()
        payload["phase14_1_action"] = enriched.decision.action
        payload["phase14_1_confidence"] = enriched.decision.confidence
        records.append(payload)

        eng = str(enriched.decision.engine or "none")
        engine_stats.setdefault(eng, []).append(enriched.calibrated.calibrated_value)
        regime_stats.setdefault(enriched.decision.regime, []).append(enriched.calibrated.calibrated_value)

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw_ds)

    comparison = summarize_calibration_comparison(records)
    write_calibration_metrics(comparison, base_dir=base_dir)
    from tradingbot.ml.confidence_engine.calibration_trace import calibration_data_dir

    cal_dir = calibration_data_dir(base_dir)
    cal_dir.mkdir(parents=True, exist_ok=True)
    (cal_dir / "calibration_events.json").write_text(
        json.dumps(calibration_events[-500:], indent=2),
        encoding="utf-8",
    )

    return {
        "records": records,
        "comparison": comparison,
        "fingerprint_before": fp_before,
        "fingerprint_after": fp_after,
        "fingerprint_unchanged": fp_before == fp_after,
        "artifact_checksums": validate_artifact_checksums(),
        "bars_processed": len(unified),
        "days": days,
        "engine_calibration_summary": {
            k: round(statistics.mean(v), 4) if v else 0.0 for k, v in engine_stats.items()
        },
        "regime_calibration_summary": {
            k: round(statistics.mean(v), 4) if v else 0.0 for k, v in regime_stats.items()
        },
    }


def validate_artifact_checksums() -> dict[str, Any]:
    p99 = phase9_9_model_path(None)
    trend_meta = phase13_4_reports_dir(None) / "trend_ml_best_model.json"
    return {
        "phase9_9_model": sha256_file(p99),
        "trend_rf_metadata": sha256_file(trend_meta),
        "phase9_9_exists": p99.is_file(),
        "trend_rf_exists": trend_meta.is_file(),
    }
