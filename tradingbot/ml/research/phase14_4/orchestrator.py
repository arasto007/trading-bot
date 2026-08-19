"""Phase 14.4 — signal optimization orchestrator."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase14_4.config import EXPECTED_FINGERPRINT, MAX_RESEARCH_BARS, phase14_4_final_report_path, phase14_4_reports_dir
from tradingbot.ml.research.phase14_4.missed_trade_analyzer import analyze_missed_trades
from tradingbot.ml.research.phase14_4.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_4.pipeline_simulator import PipelineThresholds, run_pipeline_records, trade_metrics_from_records
from tradingbot.ml.research.phase14_4.report_generator import build_final_report, write_report
from tradingbot.ml.research.phase14_4.risk_acceptance_analyzer import analyze_risk_acceptance
from tradingbot.ml.research.phase14_4.threshold_optimizer import run_threshold_search
from tradingbot.ml.research.phase14_4.trade_frequency_analyzer import analyze_trade_frequency
from tradingbot.ml.research.phase14_4.walk_forward_optimizer import run_walk_forward_optimization
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase144Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_phase14_4_optimizer(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase144Result:
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

    if len(candles) > MAX_RESEARCH_BARS:
        candles = candles.iloc[:: max(1, len(candles) // MAX_RESEARCH_BARS)]

    quick_mode = quick if quick is not None else len(candles) < 2_000

    threshold_results = run_threshold_search(
        candles, raw, symbol=symbol, timeframe=timeframe, seed=seed, quick=quick_mode
    )
    recommended = threshold_results["recommended"]
    th = PipelineThresholds(
        confidence_threshold=recommended["confidence_threshold"],
        quality_threshold=recommended["quality_threshold"],
        max_risk_percent=recommended["max_risk_percent"],
    )

    baseline_records = run_pipeline_records(
        candles, raw, symbol=symbol, timeframe=timeframe, seed=seed, thresholds=th, stride=3
    )
    missed = analyze_missed_trades(baseline_records)
    frequency = analyze_trade_frequency(baseline_records)
    risk_analysis = analyze_risk_acceptance(baseline_records)
    walk_forward = run_walk_forward_optimization(
        candles, raw, thresholds=th, symbol=symbol, timeframe=timeframe, seed=seed, quick=quick_mode or True
    )
    monte_carlo = run_monte_carlo_validation(
        baseline_records,
        simulations=50 if quick_mode else 1000,
        seed=seed,
    )

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)

    final = build_final_report(
        threshold_results=threshold_results,
        missed_trade=missed,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        frequency=frequency,
        fingerprint_unchanged=fp_before == fp_after,
        recommended=recommended,
    )

    out = phase14_4_reports_dir(base_dir)
    reports = {
        "threshold_results": write_report(out / "threshold_results.json", threshold_results),
        "confidence_results": write_report(out / "confidence_results.json", threshold_results["confidence"]),
        "quality_results": write_report(out / "quality_results.json", threshold_results["quality"]),
        "missed_trade_report": write_report(out / "missed_trade_report.json", missed),
        "walk_forward_results": write_report(out / "walk_forward_results.json", walk_forward),
        "monte_carlo_results": write_report(out / "monte_carlo_results.json", monte_carlo),
        "risk_acceptance": write_report(out / "risk_acceptance.json", risk_analysis),
        "trade_frequency": write_report(out / "trade_frequency.json", frequency),
    }

    final_payload = {
        **final,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "fingerprint_unchanged": fp_before == fp_after,
        "quick_mode": quick_mode,
        "baseline_metrics": trade_metrics_from_records(baseline_records),
        "connected_to_live_trading": False,
    }
    reports["final_phase14_4_report"] = write_report(phase14_4_final_report_path(base_dir), final_payload)

    status = final["PHASE_14_4_STATUS"]
    if fp_before != fp_after:
        status = "NEEDS_REVIEW"

    return Phase144Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "recommended": recommended,
            "baseline_trades": trade_metrics_from_records(baseline_records)["trades"],
            "walk_forward_robustness": walk_forward["robustness_score"],
            "monte_carlo_passes": monte_carlo.get("passes_gate"),
            "READY_FOR": final["READY_FOR"],
        },
    )
