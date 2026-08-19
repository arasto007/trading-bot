"""Phase 16A — validation orchestrator and report generation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.feature_alignment.config import RF_THRESHOLD, SHIFTED_FEATURES, reports_dir
from tradingbot.ml.feature_alignment.factory import build_distribution_aligner
from tradingbot.ml.feature_alignment.feature_statistics import load_live_reference_statistics, load_training_statistics
from tradingbot.ml.feature_alignment.validator import validate_aligner
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def _psi(a: np.ndarray, b: np.ndarray) -> float:
    eps = 1e-6
    if len(a) < 2 or len(b) < 2:
        return 0.0
    lo = min(float(np.min(a)), float(np.min(b)))
    hi = max(float(np.max(a)), float(np.max(b))) + eps
    br = np.linspace(lo, hi, 10)
    eh, _ = np.histogram(a, bins=br)
    ah, _ = np.histogram(b, bins=br)
    ep = eh / max(eh.sum(), 1) + eps
    ap = ah / max(ah.sum(), 1) + eps
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def _dist_stats(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {"count": 0, "max": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}
    a = np.asarray(vals, dtype=float)
    return {
        "count": int(len(a)),
        "max": round(float(np.max(a)), 6),
        "p95": round(float(np.percentile(a, 95)), 6),
        "p99": round(float(np.percentile(a, 99)), 6),
        "mean": round(float(np.mean(a)), 6),
    }


@dataclass
class Phase16AResult:
    status: str
    reports_dir: str
    before_max: float
    after_max: float
    actionable_after: int
    bundle_checksum_valid: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "16A",
            "status": self.status,
            "reports_dir": self.reports_dir,
            "before_max": self.before_max,
            "after_max": self.after_max,
            "actionable_after": self.actionable_after,
            "bundle_checksum_valid": self.bundle_checksum_valid,
        }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_phase16a_validation(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = 5,
    base_dir: str | Path | None = None,
) -> Phase16AResult:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    aligner = build_distribution_aligner(base_dir=str(base_dir) if base_dir else None, symbol=symbol)
    val = validate_aligner(aligner)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    train_stats = load_training_statistics(base_dir=base_dir, symbol=symbol, timeframe=timeframe)
    live_stats = load_live_reference_statistics(base_dir=base_dir, symbol=symbol, timeframe=timeframe)
    _write(out / "alignment_statistics.json", {
        "phase": "16A",
        "shifted_features": list(SHIFTED_FEATURES),
        "training": {k: v.to_dict() for k, v in train_stats.items()},
        "live_reference": {k: v.to_dict() for k, v in live_stats.items()},
        "validator": val,
    })

    before_probs: list[float] = []
    after_probs: list[float] = []
    before_buy = before_sell = after_buy = after_sell = 0
    shift_rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    lat_before: list[float] = []
    lat_after: list[float] = []

    trend_idx = [
        i for i in range(0, len(unified), max(1, stride))
        if rule_classify_row(unified.iloc[i]) == "TREND"
    ]

    for i in trend_idx:
        row = unified.iloc[i]
        t0 = time.perf_counter()
        pb = float(apply_trend_ml_filter(
            row, model=bundle.model, scaler=bundle.scaler,
            model_name="random_forest", threshold=RF_THRESHOLD,
        )["probability"])
        lat_before.append((time.perf_counter() - t0) * 1000)

        aligned_row = aligner.align_row(row)
        t1 = time.perf_counter()
        pa = float(apply_trend_ml_filter(
            aligned_row, model=bundle.model, scaler=bundle.scaler,
            model_name="random_forest", threshold=RF_THRESHOLD,
        )["probability"])
        lat_after.append((time.perf_counter() - t1) * 1000)

        before_probs.append(pb)
        after_probs.append(pa)
        rule = evaluate_variant_a(row, regime="TREND")

        if pb >= RF_THRESHOLD and rule == "BUY":
            before_buy += 1
        elif pb >= RF_THRESHOLD and rule == "SELL":
            before_sell += 1
        if pa >= RF_THRESHOLD and rule == "BUY":
            after_buy += 1
        elif pa >= RF_THRESHOLD and rule == "SELL":
            after_sell += 1

        if len(shift_rows) < 20:
            _, tr = aligner.align(
                {f: float(row.get(f, 0.0)) for f in bundle.feature_order}, trace=True,
            )
            shift_rows.append({
                "timestamp": str(row.get("timestamp", "")),
                "probability_before": round(pb, 6),
                "probability_after": round(pa, 6),
                "trace": tr.to_dict(),
            })

    before_d = _dist_stats(before_probs)
    after_d = _dist_stats(after_probs)
    actionable_after = after_buy + after_sell

    aligned_feats = {f: [] for f in SHIFTED_FEATURES}
    raw_feats = {f: [] for f in SHIFTED_FEATURES}
    for i in trend_idx[:500]:
        row = unified.iloc[i]
        ar = aligner.align({f: float(row.get(f, 0.0)) for f in SHIFTED_FEATURES})
        for f in SHIFTED_FEATURES:
            raw_feats[f].append(float(row.get(f, 0.0)))
            aligned_feats[f].append(float(ar[f]))

    shift_reduction = []
    for f in SHIFTED_FEATURES:
        tr_mean = train_stats[f].mean
        raw_mean = float(np.mean(raw_feats[f]))
        aligned_mean = float(np.mean(aligned_feats[f]))
        shift_reduction.append({
            "feature": f,
            "training_mean": round(tr_mean, 6),
            "live_mean_before": round(raw_mean, 6),
            "live_mean_after": round(aligned_mean, 6),
            "mean_delta_before": round(raw_mean - tr_mean, 6),
            "mean_delta_after": round(aligned_mean - tr_mean, 6),
            "psi_before": round(_psi(np.array(raw_feats[f]), train_stats[f].quantiles), 6),
            "psi_after": round(_psi(np.array(aligned_feats[f]), train_stats[f].quantiles), 6),
        })

    _write(out / "feature_shift_before_after.json", {"features": shift_reduction})
    _write(out / "probability_before_after.json", {
        "before": before_d,
        "after": after_d,
        "threshold": RF_THRESHOLD,
        "above_threshold_before": sum(1 for p in before_probs if p >= RF_THRESHOLD),
        "above_threshold_after": sum(1 for p in after_probs if p >= RF_THRESHOLD),
    })
    _write(out / "trend_signal_recovery.json", {
        "trend_bars": len(trend_idx),
        "before": {"buy": before_buy, "sell": before_sell, "actionable": before_buy + before_sell},
        "after": {"buy": after_buy, "sell": after_sell, "actionable": actionable_after},
    })
    mean_b = float(np.mean(lat_before)) if lat_before else 0.0
    mean_a = float(np.mean(lat_after)) if lat_after else 0.0
    _write(out / "latency_report.json", {
        "mean_ms_before": round(mean_b, 4),
        "mean_ms_after": round(mean_a, 4),
        "overhead_pct": round(100 * (mean_a - mean_b) / max(mean_b, 1e-9), 4),
        "within_5pct_budget": (mean_a - mean_b) / max(mean_b, 1e-9) < 0.05,
    })
    _write(out / "alignment_trace.json", {"samples": shift_rows})

    chk = validate_trend_checksum(base_dir=base_dir)
    success = (
        val["all_passed"]
        and after_d["max"] > RF_THRESHOLD
        and actionable_after > 0
        and chk.get("valid", False)
    )
    status = "READY_FOR_PHASE16B" if success else "NEEDS_REVIEW"

    final = {
        "phase": "16A",
        "status": status,
        "success_conditions": {
            "ceiling_above_0.40": after_d["max"] > RF_THRESHOLD,
            "actionable_signals": actionable_after > 0,
            "aligner_valid": val["all_passed"],
            "bundle_checksum_unchanged": chk.get("valid", False),
        },
        "before_after": {"before": before_d, "after": after_d},
        "trend_trades_recovered": actionable_after,
        "feature_shift_reduction": shift_reduction,
        "latency_overhead_pct": round(100 * (mean_a - mean_b) / max(mean_b, 1e-9), 4),
        "bundle_checksum": chk,
        "fingerprint": bundle.metadata.get("training_fingerprint"),
        "blockers": [] if success else [
            k for k, ok in {
                "ceiling": after_d["max"] > RF_THRESHOLD,
                "actionable": actionable_after > 0,
                "validator": val["all_passed"],
                "checksum": chk.get("valid", False),
            }.items() if not ok
        ],
    }
    _write(out / "phase16a_final_report.json", final)

    return Phase16AResult(
        status=status,
        reports_dir=str(out),
        before_max=float(before_d["max"]),
        after_max=float(after_d["max"]),
        actionable_after=actionable_after,
        bundle_checksum_valid=bool(chk.get("valid")),
    )
