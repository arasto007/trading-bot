"""Phase 15H — empirical frozen↔research equivalence solver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.confidence_mapping.mapping_types import MappingAnchor, MappingCurve
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter, ResearchCalibrationPolicy
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy


def _phase15g_reports_dir(base_dir: str | Path | None) -> Path:
    from tradingbot.ml.data.paths import reports_dir
    return reports_dir(base_dir) / "phase15g"


def load_phase15g_anchors(base_dir: str | Path | None = None) -> dict[str, float]:
    """Read measured ceilings from Phase 15G reports."""
    root = _phase15g_reports_dir(base_dir)
    ceiling_path = root / "confidence_ceiling.json"
    frozen_max = 0.50144
    research_max = 0.767421
    if ceiling_path.is_file():
        data = json.loads(ceiling_path.read_text(encoding="utf-8"))
        frozen_max = float(data.get("maximum_calibrated_confidence", frozen_max))
    rv_path = root / "research_vs_bundle.json"
    if rv_path.is_file():
        rv = json.loads(rv_path.read_text(encoding="utf-8"))
        diff = rv.get("confidence_diff", {})
        research_max = float(diff.get("p99", research_max))
    return {"frozen_ceiling": frozen_max, "research_ceiling": research_max}


def collect_empirical_pairs(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
    stride: int = 5,
) -> list[tuple[float, float]]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    frozen_range = getattr(registry.get("phase9_9"), "inner", None)
    frozen_trend = getattr(registry.get("trend_rf_v40"), "inner", None)
    research_range, research_trend = load_production_engines(window, symbol=symbol, seed=seed)

    policy = load_phase14_6_policy(base_dir)
    cal_th = float(policy.get("confidence_threshold", 0.30))
    frozen_method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=frozen_range, trend_engine=frozen_trend,
    )
    research_method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=research_range, trend_engine=research_trend,
    )
    frozen_ad = ResearchCalibratedAdapter(
        DecisionOrchestrator(),
        calibration_method=frozen_method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=cal_th),
    )
    research_ad = ResearchCalibratedAdapter(
        DecisionOrchestrator(),
        calibration_method=research_method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=cal_th),
    )

    pairs: list[tuple[float, float]] = []
    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx_f = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=frozen_range, trend_engine=frozen_trend,
        )
        ctx_r = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=research_range, trend_engine=research_trend,
        )
        f_cal = frozen_ad.decide(ctx_f)
        r_cal = research_ad.decide(ctx_r)
        fv = float(f_cal.final_confidence)
        rv = float(r_cal.final_confidence)
        if str(f_cal.raw_confidence.engine_signal) in ("BUY", "SELL"):
            pairs.append((fv, rv))

    return pairs


def solve_mapping_curve(
    pairs: list[tuple[float, float]],
    *,
    base_dir: str | Path | None = None,
) -> MappingCurve:
    """Build monotone mapping knots from empirical pairs + Phase 15G ceilings."""
    ceilings = load_phase15g_anchors(base_dir)
    frozen_max = float(ceilings["frozen_ceiling"])
    research_max = float(ceilings["research_ceiling"])

    anchors: list[MappingAnchor] = [MappingAnchor(0.0, 0.0, source="origin")]

    if pairs:
        arr = np.array(pairs, dtype=float)
        order = np.argsort(arr[:, 0])
        xs = arr[order, 0]
        ys = arr[order, 1]
        unique_x: dict[float, list[float]] = {}
        for x, y in zip(xs, ys, strict=False):
            unique_x.setdefault(float(x), []).append(float(y))
        for x in sorted(unique_x):
            anchors.append(
                MappingAnchor(x, float(np.median(unique_x[x])), source="empirical_pair"),
            )

    if not any(abs(a.frozen - frozen_max) < 1e-6 for a in anchors):
        anchors.append(MappingAnchor(frozen_max, research_max, source="phase15g_ceiling"))

    anchors = sorted(anchors, key=lambda a: a.frozen)
    merged: list[MappingAnchor] = []
    for a in anchors:
        if merged and abs(merged[-1].frozen - a.frozen) < 1e-9:
            merged[-1] = MappingAnchor(a.frozen, max(merged[-1].research, a.research), a.source)
        else:
            merged.append(a)

    # enforce monotonic research values
    for i in range(1, len(merged)):
        if merged[i].research < merged[i - 1].research:
            merged[i] = MappingAnchor(merged[i].frozen, merged[i - 1].research, merged[i].source)

    return MappingCurve(
        anchors=merged,
        frozen_ceiling=frozen_max,
        research_ceiling=research_max,
        method="pchip",
    )


def frozen_to_research_threshold(
    curve: MappingCurve,
    frozen_threshold: float,
    mapper: Any,
) -> float:
    return float(mapper.map(frozen_threshold))
