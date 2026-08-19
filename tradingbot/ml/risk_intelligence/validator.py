"""Phase 14.2B — integration adapter and batch validation."""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import phase13_4_reports_dir, phase9_9_model_path, reports_dir
from tradingbot.ml.confidence_engine.validator import CalibratedDecision, CalibratedDecisionAdapter
from tradingbot.ml.decision_engine.decision_types import MarketContext
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
from tradingbot.ml.risk_intelligence.risk_trace import build_risk_trace, write_risk_traces
from tradingbot.ml.risk_intelligence.risk_types import (
    AccountState,
    AdaptiveRiskContext,
    HistoricalMetrics,
    RiskRecommendation,
)

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"


def phase14_2b_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase14_2b"


def phase14_2b_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_2b_reports_dir(base_dir) / "final_report.json"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def risk_context_from_calibrated(
    market: MarketContext,
    calibrated: CalibratedDecision,
    *,
    account: AccountState | None = None,
    history: HistoricalMetrics | None = None,
) -> AdaptiveRiskContext:
    return AdaptiveRiskContext(
        market=market,
        calibrated_confidence=float(calibrated.final_confidence),
        action=str(calibrated.final_action),
        engine=calibrated.decision.engine,
        regime=calibrated.decision.regime,
        atr_percentile=float(market.volatility),
        session=market.session,
        account=account or AccountState(),
        history=history or HistoricalMetrics(),
        timestamp=calibrated.decision.timestamp,
    )


class AdaptiveRiskAdapter:
    """
    Chains Phase 14.2A calibrated decision → adaptive risk recommendation.
    Does not modify Phase 14.1 or 14.2A modules.
    """

    def __init__(
        self,
        decision_adapter: CalibratedDecisionAdapter,
        *,
        risk_engine: AdaptiveRiskEngine | None = None,
        account: AccountState | None = None,
        history: HistoricalMetrics | None = None,
    ) -> None:
        self.decision_adapter = decision_adapter
        self.risk_engine = risk_engine or AdaptiveRiskEngine()
        self.account = account or AccountState()
        self.history = history or HistoricalMetrics()

    def evaluate(self, market: MarketContext) -> tuple[CalibratedDecision, RiskRecommendation]:
        calibrated = self.decision_adapter.decide(market)
        risk_ctx = risk_context_from_calibrated(
            market,
            calibrated,
            account=self.account,
            history=self.history,
        )
        recommendation = self.risk_engine.recommend(risk_ctx)
        return calibrated, recommendation


def summarize_risk_batch(records: list[dict[str, Any]]) -> dict[str, Any]:
    risks = [float(r["risk"]["risk_percent"]) for r in records if r["risk"]["allowed"]]
    all_risks = [float(r["risk"]["risk_percent"]) for r in records]
    allowed = sum(1 for r in records if r["risk"]["allowed"])
    blocked_vol = sum(1 for r in records if r["risk"].get("blocked_by") == "volatility")
    blocked_dd = sum(1 for r in records if r["risk"].get("blocked_by") == "drawdown")
    blocked_conf = sum(1 for r in records if r["risk"].get("blocked_by") == "low_confidence")

    return {
        "total_bars": len(records),
        "allowed_count": allowed,
        "blocked_count": len(records) - allowed,
        "allowed_rate": round(allowed / len(records), 4) if records else 0.0,
        "mean_risk_allowed": round(statistics.mean(risks), 4) if risks else 0.0,
        "max_risk_observed": round(max(all_risks), 4) if all_risks else 0.0,
        "risk_within_cap": all(r <= 0.50 for r in all_risks),
        "blocked_by_volatility": blocked_vol,
        "blocked_by_drawdown": blocked_dd,
        "blocked_by_confidence": blocked_conf,
    }


def run_risk_batch(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 30,
    seed: int = 42,
    base_dir: str | Path | None = None,
    drawdown_pct: float = 0.0,
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
    peak = 10_000.0
    equity = peak * (1.0 - drawdown_pct / 100.0)
    account = AccountState(equity=equity, balance=equity, peak_equity=peak)
    history = HistoricalMetrics(engine_trade_count={"phase9_9": 3788, "trend_rf_v40": 1205})
    adapter = AdaptiveRiskAdapter(decision_adapter, account=account, history=history)

    records: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    for i in range(len(unified)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        calibrated, risk = adapter.evaluate(ctx)
        risk_ctx = risk_context_from_calibrated(ctx, calibrated, account=account, history=history)
        trace = build_risk_trace(risk_ctx, risk)
        traces.append(trace)
        records.append(
            {
                "decision": calibrated.to_dict(),
                "risk": risk.to_dict(),
                "trace": trace,
            }
        )

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw_ds)
    summary = summarize_risk_batch(records)
    write_risk_traces(traces, base_dir=base_dir)

    p99 = phase9_9_model_path(None)
    trend_meta = phase13_4_reports_dir(None) / "trend_ml_best_model.json"

    return {
        "records": records,
        "summary": summary,
        "fingerprint_before": fp_before,
        "fingerprint_after": fp_after,
        "fingerprint_unchanged": fp_before == fp_after,
        "artifact_checksums": {
            "phase9_9_model": sha256_file(p99),
            "trend_rf_metadata": sha256_file(trend_meta),
        },
        "bars_processed": len(unified),
        "days": days,
        "account_drawdown_pct": drawdown_pct,
    }
