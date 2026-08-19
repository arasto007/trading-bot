"""Phase 19C — safe profitability upgrade orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase19a.backtest import run_production_backtest
from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.phase19c.backtest import run_filtered_backtest
from tradingbot.ml.phase19c.config import BACKTEST_WINDOWS_DAYS, reports_dir
from tradingbot.ml.phase19c.filters import load_filter_settings
from tradingbot.ml.phase19c.montecarlo import run_montecarlo
from tradingbot.ml.phase19c.rollback import validate_rollback
from tradingbot.ml.phase19c.verdict import build_comparison, build_final_report, determine_verdict
from tradingbot.ml.phase19c.walkforward import run_walkforward


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def run_phase19c_upgrade(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    stride: int = 5,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    settings = load_filter_settings()

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    implementation_report = {
        "phase": "19C",
        "filters": {
            "rsi_mid": {
                "enabled": settings.enable_rsi,
                "rsi_min": settings.rsi_min,
                "rsi_max": settings.rsi_max,
            },
            "adx_band": {
                "enabled": settings.enable_adx,
                "adx_min": settings.adx_min,
                "adx_max": settings.adx_max,
            },
        },
        "integration_point": "kernel_adapter.produce_unified_signal",
        "rollback": "Set ENABLE_RSI_FILTER=false and ENABLE_ADX_FILTER=false",
        "protected_unchanged": [
            "TradingKernel",
            "RiskGate",
            "DecisionPolicy",
            "Execution",
            "MT5",
            "Bundle",
            "Calibration",
            "Confidence Mapping",
            "Feature Alignment",
            "Training",
            "Model",
        ],
    }
    _write_json(out / "implementation_report.json", implementation_report)

    windows: dict[str, Any] = {}
    phase19a_windows: dict[str, Any] = {}
    all_records: list[dict[str, Any]] = []

    for days in BACKTEST_WINDOWS_DAYS:
        label = f"{days}d"
        print(f"phase19c: filtered backtest {label} ...", flush=True)
        bt = run_filtered_backtest(
            candles,
            dataset,
            base_dir=base_dir,
            symbol=symbol,
            timeframe=timeframe,
            days=days,
            stride=stride,
            filter_settings=settings,
        )
        perf = compute_performance(bt["records"])
        windows[label] = {
            "days": days,
            "bars_evaluated": bt["bars_evaluated"],
            "filter_blocks": bt["filter_blocks"],
            "performance": perf,
        }
        if days == BACKTEST_WINDOWS_DAYS[-1]:
            all_records = bt["records"]

        print(f"phase19c: phase19a baseline {label} ...", flush=True)
        base_bt = run_production_backtest(
            candles,
            dataset,
            base_dir=base_dir,
            symbol=symbol,
            timeframe=timeframe,
            days=days,
            stride=stride,
        )
        phase19a_windows[label] = compute_performance(base_bt["records"])

    filter_validation = {
        "phase": "19C",
        "filter_settings": settings.to_dict(),
        "windows": windows,
        "total_filter_blocks_3y": windows.get("1095d", {}).get("filter_blocks", 0),
    }
    _write_json(out / "filter_validation.json", filter_validation)

    print("phase19c: rollback validation ...", flush=True)
    rollback = validate_rollback(
        candles,
        dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=BACKTEST_WINDOWS_DAYS[-1],
        stride=stride,
    )
    _write_json(out / "rollback_validation.json", rollback)

    comparison = build_comparison(
        phase19a_perf=phase19a_windows.get("1095d", {}),
        phase19c_perf=windows.get("1095d", {}).get("performance", {}),
        days=BACKTEST_WINDOWS_DAYS[-1],
        rollback=rollback,
    )
    performance_comparison = {
        "phase": "19C",
        "windows_19a": phase19a_windows,
        "windows_19c": {k: v.get("performance") for k, v in windows.items()},
        "comparison_3y": comparison,
    }
    _write_json(out / "performance_comparison.json", performance_comparison)

    print("phase19c: walk-forward ...", flush=True)
    walkforward = run_walkforward(all_records)
    _write_json(out / "walkforward_results.json", walkforward)

    print("phase19c: monte carlo ...", flush=True)
    montecarlo = run_montecarlo(all_records)
    _write_json(out / "montecarlo_results.json", montecarlo)

    verdict = determine_verdict(
        comparison_3y=comparison,
        rollback=rollback,
        walkforward=walkforward,
        montecarlo=montecarlo,
    )
    final = build_final_report(
        verdict=verdict,
        filter_settings=settings.to_dict(),
        comparison=comparison,
        windows=windows,
        rollback=rollback,
        walkforward=walkforward,
        montecarlo=montecarlo,
    )
    _write_json(out / "phase19c_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "comparison": comparison,
        "rollback": rollback,
    }
