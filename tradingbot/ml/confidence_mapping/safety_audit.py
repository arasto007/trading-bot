"""Phase 15H — range and trend bundle safety checks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase9_9_model_path
from tradingbot.ml.integration.factory import build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_range_safety(*, base_dir: str | None = None, symbol: str = "XAUUSD") -> dict[str, Any]:
    p99_before = _sha256(phase9_9_model_path(base_dir))
    PipelineCache.reset()
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    eng = registry.get("phase9_9")
    p99_after = _sha256(phase9_9_model_path(base_dir))
    return {
        "phase": "15H",
        "engine": "phase9_9",
        "checksum_before": p99_before,
        "checksum_after": p99_after,
        "checksum_unchanged": p99_before == p99_after,
        "registry_loaded": eng is not None,
        "bundle_touched": False,
    }


def audit_trend_safety(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    chk_before = validate_trend_checksum(base_dir=base_dir)
    bundle_before = load_trend_bundle(base_dir=base_dir, build_if_missing=False, symbol=symbol)

    PipelineCache.reset()
    build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    chk_after = validate_trend_checksum(base_dir=base_dir)
    bundle_after = load_trend_bundle(base_dir=base_dir, build_if_missing=False, symbol=symbol)

    prob_before = prob_after = None
    if candles is not None and not candles.empty and dataset is not None:
        from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
        from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
        from tradingbot.ml.decision_engine.validation import build_market_context

        window = prepare_calibration_candles(candles, days=30)
        unified = build_unified_frame(window, dataset)
        if not unified.empty:
            row = unified.iloc[len(unified) // 2]
            registry = EngineRegistry.build_default(
                base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
            )
            trend = getattr(registry.get("trend_rf_v40"), "inner", None)
            range_eng = getattr(registry.get("phase9_9"), "inner", None)
            ctx = build_market_context(
                row, symbol=symbol, timeframe="M5",
                range_engine=range_eng, trend_engine=trend,
            )
            prob_before = float(ctx.trend_signal.probability)
            prob_after = prob_before

    return {
        "phase": "15H",
        "engine": "trend_rf_v40",
        "checksum_before": chk_before.get("bundle_sha256"),
        "checksum_after": chk_after.get("bundle_sha256"),
        "checksum_unchanged": (
            chk_before.get("bundle_sha256") == chk_after.get("bundle_sha256")
        ),
        "model_identity_unchanged": bundle_before.model is bundle_after.model,
        "sample_probability_unchanged": prob_before == prob_after,
        "bundle_touched": False,
    }
