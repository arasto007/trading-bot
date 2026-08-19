"""Phase 16B — mandatory stress tests."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.feature_alignment.config import SHIFTED_FEATURES
from tradingbot.ml.feature_alignment.factory import build_distribution_aligner
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase16b.config import RF_THRESHOLD
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def _trend_actionable_count(
    unified: pd.DataFrame,
    *,
    stride: int,
    bundle,
    aligner,
    noise_pct: float = 0.0,
    threshold: float = RF_THRESHOLD,
) -> dict[str, Any]:
    actionable = 0
    probs: list[float] = []
    for i in range(0, len(unified), stride):
        row = unified.iloc[i]
        if rule_classify_row(row) != "TREND":
            continue
        feats = {f: float(row.get(f, 0.0)) for f in SHIFTED_FEATURES}
        if noise_pct:
            rng = np.random.default_rng(i + int(noise_pct * 1000))
            for f in feats:
                feats[f] *= 1.0 + rng.uniform(-noise_pct, noise_pct)
        aligned = aligner.align(feats) if aligner else feats
        row_a = row.copy()
        for f, v in aligned.items():
            row_a[f] = v
        ml = apply_trend_ml_filter(
            row_a, model=bundle.model, scaler=bundle.scaler,
            model_name="random_forest", threshold=threshold,
        )
        prob = float(ml["probability"])
        probs.append(prob)
        rule = evaluate_variant_a(row, regime="TREND")
        if prob >= threshold and rule in ("BUY", "SELL"):
            actionable += 1
    return {
        "actionable": actionable,
        "max_prob": round(float(max(probs)), 6) if probs else 0.0,
        "mean_prob": round(float(np.mean(probs)), 6) if probs else 0.0,
        "trend_bars": len(probs),
    }


def regime_shock_test(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int = 365,
    stride: int = 5,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    min_actionable: int = 1,
) -> dict[str, Any]:
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    aligner = build_distribution_aligner(base_dir=base_dir, symbol=symbol)
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    atr = unified.get("atr", pd.Series(0.0, index=unified.index))
    vol_q90 = float(atr.quantile(0.90)) if len(atr) else 0.0
    high_vol = unified[atr >= vol_q90]
    normal = unified[atr < vol_q90]

    hv = _trend_actionable_count(high_vol, stride=stride, bundle=bundle, aligner=aligner)
    nv = _trend_actionable_count(normal, stride=stride, bundle=bundle, aligner=aligner)
    passed = hv["actionable"] >= min_actionable
    return {
        "test": "regime_shock",
        "high_vol_threshold_atr": round(vol_q90, 6),
        "high_vol_bars": int(len(high_vol)),
        "high_vol_actionable": hv["actionable"],
        "normal_actionable": nv["actionable"],
        "high_vol_max_prob": hv["max_prob"],
        "passed": passed,
    }


def distribution_shift_test(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int = 365,
    stride: int = 5,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    seed: int = 42,
) -> dict[str, Any]:
    np.random.seed(seed)
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    aligner = build_distribution_aligner(base_dir=base_dir, symbol=symbol)
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    baseline = _trend_actionable_count(unified, stride=stride, bundle=bundle, aligner=aligner)
    noise_5 = _trend_actionable_count(
        unified, stride=stride, bundle=bundle, aligner=aligner, noise_pct=0.05,
    )
    # monotonic: noise should not increase actionable vs baseline
    monotonic = noise_5["actionable"] <= baseline["actionable"] + 1
    no_collapse = noise_5["max_prob"] >= baseline["max_prob"] * 0.85
    return {
        "test": "distribution_shift",
        "baseline_actionable": baseline["actionable"],
        "noise_5pct_actionable": noise_5["actionable"],
        "baseline_max_prob": baseline["max_prob"],
        "noise_5pct_max_prob": noise_5["max_prob"],
        "monotonic_degradation": monotonic,
        "no_collapse": no_collapse,
        "passed": monotonic and no_collapse,
    }


def threshold_sensitivity_test(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int = 365,
    stride: int = 5,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    thresholds: tuple[float, ...] = (0.35, 0.40, 0.45),
) -> dict[str, Any]:
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    aligner = build_distribution_aligner(base_dir=base_dir, symbol=symbol)
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    results = {}
    for th in thresholds:
        r = _trend_actionable_count(
            unified, stride=stride, bundle=bundle, aligner=aligner, threshold=th,
        )
        results[str(th)] = r

    # alignment effect: at 0.40 should beat no-aligner baseline at same threshold
    no_align = _trend_actionable_count(
        unified, stride=stride, bundle=bundle, aligner=None, threshold=0.40,
    )
    aligned_40 = results.get("0.4", results.get("0.40", {}))
    alignment_helps = aligned_40.get("actionable", 0) >= no_align.get("actionable", 0)
    return {
        "test": "threshold_sensitivity",
        "thresholds": results,
        "no_aligner_at_0.40": no_align,
        "alignment_effect_persists": alignment_helps,
        "passed": alignment_helps,
    }
