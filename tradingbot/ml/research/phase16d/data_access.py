"""Phase 16D — TREND bar dataset with frozen bundle probabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np
import pandas as pd

from tradingbot.ml.feature_alignment.factory import build_distribution_aligner
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle, load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase16d.candidate_compute import CANDIDATE_FEATURE_IDS, compute_candidate_features
from tradingbot.ml.research.phase16d.config import RF_THRESHOLD
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


@dataclass
class TrendBarRecord:
    timestamp: str
    probability: float
    rule_direction: str
    win_proxy: int
    existing: dict[str, float]
    candidates: dict[str, float]
    adx: float
    atr_percentile: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "probability": round(self.probability, 6),
            "rule_direction": self.rule_direction,
            "win_proxy": self.win_proxy,
            "existing": self.existing,
            "candidates": self.candidates,
            "adx": self.adx,
            "atr_percentile": self.atr_percentile,
        }


def _win_proxy(frame: pd.DataFrame, i: int, direction: str, *, horizon: int = 12) -> int:
    if direction not in ("BUY", "SELL") or i + horizon >= len(frame):
        return 0
    entry = float(frame.iloc[i]["close"])
    future = float(frame.iloc[i + horizon]["close"])
    ret = (future - entry) / max(abs(entry), 1e-12)
    if direction == "BUY":
        return 1 if ret > 0.0005 else 0
    return 1 if ret < -0.0005 else 0


def collect_trend_records(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    days: int = 365,
    stride: int = 5,
) -> tuple[list[TrendBarRecord], TrendRfBundle, pd.DataFrame]:
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    aligner = build_distribution_aligner(base_dir=base_dir, symbol=symbol)
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    enriched = compute_candidate_features(unified)

    records: list[TrendBarRecord] = []
    for i in range(0, len(enriched), max(1, stride)):
        row = enriched.iloc[i]
        if rule_classify_row(row) != "TREND":
            continue
        aligned = aligner.align_row(row) if aligner else row
        ml = apply_trend_ml_filter(
            aligned, model=bundle.model, scaler=bundle.scaler,
            model_name="random_forest", threshold=RF_THRESHOLD,
        )
        rule_dir = evaluate_variant_a(row, regime="TREND")
        prob = float(ml["probability"])
        existing = {f: float(row.get(f, 0.0)) for f in bundle.feature_order}
        candidates = {f: float(row.get(f, 0.0)) for f in CANDIDATE_FEATURE_IDS}
        win = _win_proxy(enriched, i, rule_dir)
        records.append(TrendBarRecord(
            timestamp=str(row.get("timestamp", "")),
            probability=prob,
            rule_direction=rule_dir,
            win_proxy=win,
            existing=existing,
            candidates=candidates,
            adx=float(row.get("adx", 0)),
            atr_percentile=float(row.get("atr_percentile", 0)),
        ))
    return records, bundle, enriched
