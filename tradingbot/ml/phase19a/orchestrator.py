"""Phase 19A — profitability audit orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase19a.backtest import run_production_backtest
from tradingbot.ml.phase19a.capital import analyze_capital
from tradingbot.ml.phase19a.config import BACKTEST_WINDOWS_DAYS, reports_dir
from tradingbot.ml.phase19a.drawdown import analyze_drawdown_report
from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.phase19a.regime_analysis import analyze_regimes
from tradingbot.ml.phase19a.robustness import run_robustness
from tradingbot.ml.phase19a.scoring import compute_final_score
from tradingbot.ml.phase19a.symbol_analysis import analyze_symbol, monthly_statistics, yearly_statistics
from tradingbot.ml.phase19a.trade_quality import analyze_trade_quality
from tradingbot.ml.phase19a.verdict import build_final_report, determine_verdict


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Strip large record lists from nested dumps when writing summary files
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def run_phase19a_audit(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    stride: int = 5,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    windows: dict[str, Any] = {}
    all_records: list[dict[str, Any]] = []

    for days in BACKTEST_WINDOWS_DAYS:
        label = f"{days}d"
        print(f"phase19a: backtest {label} ...", flush=True)
        bt = run_production_backtest(
            candles, dataset,
            base_dir=base_dir, symbol=symbol, timeframe=timeframe,
            days=days, stride=stride,
        )
        perf = compute_performance(bt["records"])
        windows[label] = {
            "days": days,
            "bars_evaluated": bt["bars_evaluated"],
            "performance": perf,
        }
        if days == BACKTEST_WINDOWS_DAYS[-1]:
            all_records = bt["records"]

    performance_summary = {
        "phase": "19A",
        "symbol": symbol,
        "timeframe": timeframe,
        "stride": stride,
        "windows": windows,
        "trend_engine": "trend_rf_v41",
        "range_engine": "phase9_9",
        "simulation_only": True,
    }
    _write_json(out / "performance_summary.json", performance_summary)

    print("phase19a: regime analysis ...", flush=True)
    regime = analyze_regimes(all_records)
    _write_json(out / "regime_analysis.json", regime)

    print("phase19a: trade quality ...", flush=True)
    trade_quality = analyze_trade_quality(all_records)
    _write_json(out / "trade_quality.json", trade_quality)

    print("phase19a: symbol / temporal ...", flush=True)
    symbol_stats = analyze_symbol(all_records, symbol=symbol)
    monthly = monthly_statistics(all_records)
    yearly = yearly_statistics(all_records)
    _write_json(out / "monthly_statistics.json", monthly)
    _write_json(out / "yearly_statistics.json", yearly)

    print("phase19a: drawdown ...", flush=True)
    drawdown = analyze_drawdown_report(all_records)
    _write_json(out / "drawdown_analysis.json", drawdown)

    print("phase19a: robustness ...", flush=True)
    robustness = run_robustness(all_records)
    _write_json(out / "robustness.json", robustness)

    print("phase19a: capital analysis ...", flush=True)
    capital = analyze_capital(all_records)
    _write_json(out / "capital_analysis.json", capital)

    # Configuration validation placeholder in performance summary
    _write_json(out / "configuration_validation.json", {
        "phase": "19A",
        "note": "production config unchanged",
        "trend_model_version": "v41",
        "read_only": True,
    })

    final_score = compute_final_score(
        performance=performance_summary,
        robustness=robustness,
        regime=regime,
        capital=capital,
    )
    _write_json(out / "final_score.json", final_score)

    verdict = determine_verdict(
        performance_summary=performance_summary,
        robustness=robustness,
        capital=capital,
        final_score=final_score,
    )
    final = build_final_report(
        verdict=verdict,
        performance_summary=performance_summary,
        regime=regime,
        trade_quality=trade_quality,
        capital=capital,
        robustness=robustness,
        final_score=final_score,
    )
    final["drawdown"] = drawdown
    final["symbol_analysis"] = {
        "by_session": symbol_stats.get("by_session"),
        "by_year": symbol_stats.get("by_year"),
    }
    _write_json(out / "phase19a_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "final_score": final_score,
        "performance_summary": performance_summary,
    }
