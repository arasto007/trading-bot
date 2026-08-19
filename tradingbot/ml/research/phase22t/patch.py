"""Phase 22T — research-only patch: live FeatureBuilder for range engine phase99 features."""

from __future__ import annotations

import contextlib
from typing import Any, Generator

import pandas as pd

from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.integration.factory import MLKernelStack, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.config import RANGE_ENGINE_ID
from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
from tradingbot.ml.research.phase22f.config import configure_research_env
from tradingbot.ml.research.phase22t.config import use_live_phase99_features


_candles_ctx: dict[str, Any] = {"df": None, "idx": None}
_ORIGINAL_GET_UNIFIED = PipelineCache.get_unified_frame.__func__


def _capture_candles(cls, candles, *, base_dir=None, symbol="XAUUSD", timeframe="M5"):
    unified = _ORIGINAL_GET_UNIFIED(
        cls, candles, base_dir=base_dir, symbol=symbol, timeframe=timeframe,
    )
    if candles is not None and not candles.empty:
        _candles_ctx["df"] = candles
        _candles_ctx["idx"] = len(candles) - 1
    return unified


def _patch_unified_range_eval(wrapped, *, base_dir: str | None, symbol: str) -> None:
    """Patch UnifiedRangeWrapper.evaluate to inject FeatureBuilder features when flag is on."""
    unified = getattr(wrapped, "inner", wrapped)
    adapter = getattr(unified, "_inner", None)
    if adapter is None:
        return

    fb = FeatureBuilder(symbol=symbol, base_dir=base_dir)
    orig_eval = unified.evaluate

    def _evaluate(*, row: pd.Series, **kwargs: Any) -> dict[str, Any]:
        if not use_live_phase99_features():
            return orig_eval(row=row, **kwargs)
        candles = _candles_ctx.get("df")
        idx = _candles_ctx.get("idx")
        if candles is not None and idx is not None:
            live = fb.compute_at(candles, int(idx))
            feat_row = row.copy()
            for f in adapter.bundle.feature_order:
                feat_row[f] = float(live.get(f, 0.0))
            return adapter.evaluate(row=feat_row, **kwargs)
        return orig_eval(row=row_for_phase99_range(row), **kwargs)

    unified.evaluate = _evaluate  # type: ignore[method-assign]


def apply_live_patch(registry, *, base_dir: str | None, symbol: str = "XAUUSD") -> None:
    if not use_live_phase99_features():
        return
    wrapped = registry.get(RANGE_ENGINE_ID)
    if wrapped is None:
        return
    _patch_unified_range_eval(wrapped, base_dir=base_dir, symbol=symbol)
    PipelineCache.get_unified_frame = classmethod(_capture_candles)  # type: ignore[method-assign]


def reset_patch_state() -> None:
    _candles_ctx["df"] = None
    _candles_ctx["idx"] = None
    PipelineCache.get_unified_frame = classmethod(_ORIGINAL_GET_UNIFIED)  # type: ignore[method-assign]
    PipelineCache.reset()


@contextlib.contextmanager
def research_stack(*, base_dir: str | None, use_live: bool) -> Generator[MLKernelStack, None, None]:
    import tradingbot.ml.integration.factory as factory

    from tradingbot.ml.research.phase22t.config import set_live_phase99_features

    configure_research_env()
    set_live_phase99_features(use_live)
    reset_patch_state()
    stack = build_ml_kernel_stack(base_dir=base_dir)
    apply_live_patch(stack.registry, base_dir=base_dir)
    original = factory.build_ml_kernel_stack
    factory.build_ml_kernel_stack = lambda **kwargs: stack
    try:
        yield stack
    finally:
        factory.build_ml_kernel_stack = original
        reset_patch_state()
        set_live_phase99_features(False)
