"""Phase 16B — orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase16b.alignment_metrics import alignment_metrics_for_window
from tradingbot.ml.research.phase16b.config import reports_dir
from tradingbot.ml.research.phase16b.kernel_replay import (
    replay_kernel_window,
    replay_without_aligner_baseline,
)
from tradingbot.ml.research.phase16b.stress_tests import (
    distribution_shift_test,
    regime_shock_test,
    threshold_sensitivity_test,
)
from tradingbot.ml.research.phase16b.validator import final_verdict, run_hard_checks
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def _load_candles_dataset(symbol: str, timeframe: str, base_dir: str | None) -> tuple:
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")
    return candles, dataset


def _regime_breakdown(candles, dataset, days: int, stride: int, symbol: str, base_dir) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    unified = build_unified_frame(window, dataset)
    counts: dict[str, int] = {}
    for i in range(0, len(unified), stride):
        r = rule_classify_row(unified.iloc[i])
        counts[r] = counts.get(r, 0) + 1
    total = sum(counts.values()) or 1
    return {
        "days": days,
        "stride": stride,
        "regime_counts": counts,
        "regime_pct": {k: round(v / total, 4) for k, v in counts.items()},
    }


def run_phase16b(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    windows: tuple[int, ...] = (90, 180, 365),
    strides: tuple[int, ...] = (5, 10),
    seed: int = 42,
    base_dir: str | None = None,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    candles, dataset = _load_candles_dataset(symbol, timeframe, base_dir)

    window_reports: dict[str, Any] = {}
    alignment_rows: list[dict[str, Any]] = []
    regime_rows: list[dict[str, Any]] = []
    inflation_samples: list[float] = []

    for days in windows:
        stride_results: dict[str, Any] = {}
        for stride in strides:
            print(f"phase16b: window={days}d stride={stride} ...", flush=True)
            replay = replay_kernel_window(
                candles, dataset, days=days, stride=stride,
                symbol=symbol, timeframe=timeframe, base_dir=base_dir,
            )
            align = alignment_metrics_for_window(
                candles, dataset, days=days, stride=stride,
                base_dir=base_dir, symbol=symbol,
            )
            stride_results[str(stride)] = {**replay, "alignment": align}
            alignment_rows.append(align)
            regime_rows.append(_regime_breakdown(candles, dataset, days, stride, symbol, base_dir))

            with_align = replay["engine_health"]["TREND"]["buy"] + replay["engine_health"]["TREND"]["sell"]
            without = replay_without_aligner_baseline(
                candles, dataset, days=days, stride=stride, symbol=symbol, base_dir=base_dir,
            )
            # Recovery from zero is not inflation; only relative growth when baseline > 0.
            if without > 0:
                inflation_samples.append(max(0.0, (with_align - without) / without * 100.0))
            else:
                inflation_samples.append(0.0)

        window_reports[f"{days}d"] = {"days": days, "strides": stride_results}
        (out / f"window_{days}d.json").write_text(
            json.dumps(window_reports[f"{days}d"], indent=2), encoding="utf-8",
        )

    alignment_stability = {
        "per_window_stride": alignment_rows,
        "max_psi_after": max((r.get("max_psi_after", 0) for r in alignment_rows), default=0.0),
        "mean_drift_index": round(
            sum(r.get("drift_index", 0) for r in alignment_rows) / max(len(alignment_rows), 1), 6,
        ),
        "cross_window_psi_variance": round(
            float(
                sum(
                    (r.get("drift_index", 0) - sum(x.get("drift_index", 0) for x in alignment_rows) / max(len(alignment_rows), 1)) ** 2
                    for r in alignment_rows
                ) / max(len(alignment_rows), 1)
            ),
            6,
        ),
    }
    (out / "alignment_stability.json").write_text(json.dumps(alignment_stability, indent=2), encoding="utf-8")

    regime_breakdown = {"windows": regime_rows}
    (out / "regime_breakdown.json").write_text(json.dumps(regime_breakdown, indent=2), encoding="utf-8")

    print("phase16b: stress tests ...", flush=True)
    stress = {
        "regime_shock": regime_shock_test(candles, dataset, base_dir=base_dir, symbol=symbol),
        "distribution_shift": distribution_shift_test(candles, dataset, seed=seed, base_dir=base_dir, symbol=symbol),
        "threshold_sensitivity": threshold_sensitivity_test(candles, dataset, base_dir=base_dir, symbol=symbol),
    }
    (out / "stress_test_results.json").write_text(json.dumps(stress, indent=2), encoding="utf-8")
    (out / "threshold_sensitivity.json").write_text(
        json.dumps(stress["threshold_sensitivity"], indent=2), encoding="utf-8",
    )

    inflation_pct = max(inflation_samples) if inflation_samples else 0.0
    hard = run_hard_checks(
        windows=window_reports,
        alignment_stability=alignment_stability,
        inflation_pct=inflation_pct,
    )
    verdict = final_verdict(hard, window_reports, stress)

    cross_variance = []
    for wk, wdata in window_reports.items():
        for sd in wdata.get("strides", {}).values():
            cross_variance.append(sd.get("stability_proxy", {}).get("expectancy_proxy", 0.0))

    final_report = {
        "phase": "16B",
        "symbol": symbol,
        "timeframe": timeframe,
        "windows": list(windows),
        "strides": list(strides),
        "seed": seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "hard_checks": hard,
        "signal_inflation_pct_max": round(inflation_pct, 2),
        "cross_window_expectancy_variance": round(
            sum((x - sum(cross_variance) / max(len(cross_variance), 1)) ** 2 for x in cross_variance)
            / max(len(cross_variance), 1),
            6,
        ) if cross_variance else 0.0,
        "summary": {
            wk: {
                st: {
                    "kernel_actionable": sd.get("kernel", {}).get("actionable"),
                    "trend_engine_actionable": sd.get("engine_health", {}).get("TREND", {}).get("buy", 0)
                    + sd.get("engine_health", {}).get("TREND", {}).get("sell", 0),
                    "range_engine_actionable": sd.get("engine_health", {}).get("RANGE", {}).get("buy", 0)
                    + sd.get("engine_health", {}).get("RANGE", {}).get("sell", 0),
                    "trend_max_prob": sd.get("engine_health", {}).get("TREND", {}).get("probability", {}).get("max"),
                }
                for st, sd in wdata.get("strides", {}).items()
            }
            for wk, wdata in window_reports.items()
        },
        "stress_passed": all(stress[k].get("passed", False) for k in stress),
    }
    (out / "final_phase16b_report.json").write_text(json.dumps(final_report, indent=2), encoding="utf-8")

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final_report,
    }
