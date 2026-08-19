#!/usr/bin/env python3
"""Phase 22T — controlled live FeatureBuilder refactor comparison on Dataset A."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


async def _main_async() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase22f.config import build_dataset
    from tradingbot.ml.research.phase22t.compare import profile_range_signals
    from tradingbot.ml.research.phase22t.config import ENV_FLAG, VERDICT_EFFECT_THRESHOLD_PCT
    from tradingbot.ml.research.phase22t.runner import (
        compare_runs,
        determine_verdict,
        run_dataset_a_backtest,
    )

    now = datetime.now(timezone.utc).isoformat()
    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(legacy.get("BASE_DIR"))
    dataset = build_dataset("A")

    print("Phase 22T — Dataset A baseline (current repository)...", flush=True)
    baseline_bt = await run_dataset_a_backtest(dataset, use_live=False, base_dir=base_dir)
    baseline_sig = await profile_range_signals(dataset, use_live=False, base_dir=base_dir)

    print("Phase 22T — Dataset A live (FeatureBuilder)...", flush=True)
    live_bt = await run_dataset_a_backtest(dataset, use_live=True, base_dir=base_dir)
    live_sig = await profile_range_signals(dataset, use_live=True, base_dir=base_dir)

    trade_delta = compare_runs(baseline_bt, live_bt)
    verdict = determine_verdict(baseline_bt, live_bt, baseline_sig, live_sig)

    baseline_vs_live = {
        "phase": "22T",
        "generated_utc": now,
        "dataset": dataset.to_dict(),
        "feature_flag": ENV_FLAG,
        "baseline_mode": "current_repository (row_for_phase99_range)",
        "live_mode": "FeatureBuilder.compute_at via RESEARCH_USE_LIVE_PHASE99_FEATURES",
        "production_modified": False,
        "backtest_baseline": baseline_bt,
        "backtest_live": live_bt,
        "trade_comparison": trade_delta,
        "verdict": verdict,
    }

    signal_comparison = {
        "phase": "22T",
        "generated_utc": now,
        "baseline": baseline_sig,
        "live": live_sig,
        "p_win_delta": {
            "mean": round(
                live_sig.get("p_win", {}).get("mean", 0) - baseline_sig.get("p_win", {}).get("mean", 0),
                6,
            ),
        },
        "engine_hold_delta": (live_sig.get("engine_hold", 0) - baseline_sig.get("engine_hold", 0)),
        "signal_density_delta_pct": round(
            (live_sig.get("signal_density_pct") or 0) - (baseline_sig.get("signal_density_pct") or 0),
            4,
        ),
    }

    feature_validation = {
        "phase": "22T",
        "generated_utc": now,
        "features_changed": ["structure_distance", "ema50_slope", "candle_direction"],
        "only_source_changed": True,
        "model_threshold_calibration_unchanged": True,
        "diff_samples_baseline_vs_live": baseline_sig.get("feature_diff_samples", []),
        "bars_with_feature_diff_in_sample": baseline_sig.get("feature_diff_sample_count", 0),
    }

    final = {
        "phase": "22T",
        "title": "Controlled Live FeatureBuilder Refactor (Research Branch)",
        "generated_utc": now,
        "production_modified": False,
        "feature_flag": ENV_FLAG,
        "dataset_a": dataset.to_dict(),
        "verdict": verdict,
        "effect_threshold_pct": VERDICT_EFFECT_THRESHOLD_PCT,
        "baseline_backtest": {
            k: baseline_bt.get(k) for k in (
                "BUY", "SELL", "signal_density_pct", "decision_hold",
                "trade_count", "profit_factor", "expectancy",
            )
        },
        "live_backtest": {
            k: live_bt.get(k) for k in (
                "BUY", "SELL", "signal_density_pct", "decision_hold",
                "trade_count", "profit_factor", "expectancy",
            )
        },
        "baseline_range_signals": baseline_sig.get("signals"),
        "live_range_signals": live_sig.get("signals"),
        "baseline_p_win_mean": baseline_sig.get("p_win", {}).get("mean"),
        "live_p_win_mean": live_sig.get("p_win", {}).get("mean"),
        "summary": _summary(verdict, baseline_bt, live_bt, baseline_sig, live_sig),
    }

    _write("baseline_vs_live.json", baseline_vs_live)
    _write("signal_comparison.json", signal_comparison)
    _write("trade_comparison.json", {
        "phase": "22T",
        "generated_utc": now,
        "comparison": trade_delta,
        "baseline": baseline_bt,
        "live": live_bt,
    })
    _write("feature_source_validation.json", feature_validation)
    _write("phase22t_final_report.json", final)

    print(json.dumps({"verdict": verdict, "baseline": baseline_bt, "live": live_bt}, indent=2))
    return 0


def _summary(
    verdict: str,
    baseline_bt: dict,
    live_bt: dict,
    baseline_sig: dict,
    live_sig: dict,
) -> str:
    parts = [f"Verdict={verdict}."]
    for label, bt, sig in (("baseline", baseline_bt, baseline_sig), ("live", live_bt, live_sig)):
        parts.append(
            f"{label}: trades={bt.get('trade_count')} PF={bt.get('profit_factor')} "
            f"BUY={bt.get('BUY')} SELL={bt.get('SELL')} decision_hold={bt.get('decision_hold')} "
            f"range_BUY={sig.get('signals', {}).get('BUY')} range_SELL={sig.get('signals', {}).get('SELL')} "
            f"P(win)_mean={sig.get('p_win', {}).get('mean')}."
        )
    return " ".join(parts)


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
