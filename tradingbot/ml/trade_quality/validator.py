"""Phase 14.3 — batch validation and reporting."""

from __future__ import annotations

import hashlib
import statistics
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import phase13_4_reports_dir, phase9_9_model_path, reports_dir
from tradingbot.ml.confidence_engine.validator import CalibratedDecisionAdapter
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.risk_intelligence.risk_types import AccountState, HistoricalMetrics
from tradingbot.ml.risk_intelligence.validator import AdaptiveRiskAdapter
from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter, build_quality_context
from tradingbot.ml.trade_quality.quality_trace import build_quality_trace, write_quality_traces

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"


def phase14_3_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase14_3"


def phase14_3_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_3_reports_dir(base_dir) / "final_report.json"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_quality_batch(records: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(r["quality"]["score"]) for r in records]
    allowed = [r for r in records if r["quality"]["allowed"]]
    blocked = [r for r in records if not r["quality"]["allowed"]]
    grades: dict[str, int] = {}
    for r in records:
        g = str(r["quality"]["grade"])
        grades[g] = grades.get(g, 0) + 1

    risk_allowed = sum(1 for r in records if r["risk"]["allowed"])
    quality_allowed = len(allowed)

    return {
        "total_bars": len(records),
        "risk_allowed": risk_allowed,
        "quality_allowed": quality_allowed,
        "quality_blocked": len(blocked),
        "acceptance_rate": round(quality_allowed / len(records), 4) if records else 0.0,
        "mean_score": round(statistics.mean(scores), 4) if scores else 0.0,
        "mean_score_allowed": round(statistics.mean([float(r["quality"]["score"]) for r in allowed]), 4)
        if allowed
        else 0.0,
        "grade_distribution": grades,
        "blocked_reasons": _blocked_counts(blocked),
    }


def _blocked_counts(blocked: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in blocked:
        key = str(r["quality"].get("blocked_by") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def run_quality_batch(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 30,
    seed: int = 42,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore

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
    decision_adapter = CalibratedDecisionAdapter(orchestrator)
    account = AccountState()
    history = HistoricalMetrics(engine_trade_count={"phase9_9": 3788, "trend_rf_v40": 1205})
    risk_adapter = AdaptiveRiskAdapter(decision_adapter, account=account, history=history)
    adapter = TradeQualityAdapter(risk_adapter)

    records: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    blocked_trades: list[dict[str, Any]] = []

    for i in range(len(unified)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        calibrated, risk, quality = adapter.evaluate(ctx)
        qctx = build_quality_context(ctx, calibrated, risk)
        trace = build_quality_trace(qctx, quality)
        traces.append(trace)
        record = {
            "decision": calibrated.to_dict(),
            "risk": risk.to_dict(),
            "quality": quality.to_dict(),
            "trace": trace,
        }
        records.append(record)
        if not quality.allowed and calibrated.final_action in ("BUY", "SELL"):
            blocked_trades.append(record)
        elif not quality.allowed and risk.allowed:
            blocked_trades.append(record)

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw_ds)
    summary = summarize_quality_batch(records)
    write_quality_traces(traces, base_dir=base_dir)

    p99 = phase9_9_model_path(None)
    trend_meta = phase13_4_reports_dir(None) / "trend_ml_best_model.json"

    return {
        "records": records,
        "summary": summary,
        "blocked_trades": blocked_trades[:200],
        "fingerprint_before": fp_before,
        "fingerprint_after": fp_after,
        "fingerprint_unchanged": fp_before == fp_after,
        "artifact_checksums": {
            "phase9_9_model": sha256_file(p99),
            "trend_rf_metadata": sha256_file(trend_meta),
        },
        "bars_processed": len(unified),
        "days": days,
    }
