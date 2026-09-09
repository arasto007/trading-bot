"""Shared tmp fixture for Phase 15B/15C/15D kernel tests.

Production resolver defaults to trend_rf_v41. These tests must populate the
temporary tree with the real v41 bundle (plus v40, which EngineRegistry still
loads) instead of freezing only the legacy v40 path.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

_RESEARCH_BUNDLES = (
    "trend_rf_bundle",
    "trend_rf_bundle_v41",
)


def setup_kernel_tmp(
    tmp: str,
    *,
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None = None,
    copy_phase99: bool = True,
) -> None:
    """Install candles, dataset, phase9.9, and v40+v41 trend bundles under tmp."""
    from tradingbot.ml.data.stores import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.feature_alignment.factory import build_distribution_aligner
    from tradingbot.ml.integration.pipeline_cache import PipelineCache

    PipelineCache.reset()
    build_distribution_aligner.cache_clear()

    research_dst = Path(tmp) / "ml" / "research"
    research_dst.mkdir(parents=True, exist_ok=True)
    research_src = ROOT / "data" / "ml" / "research"

    if copy_phase99:
        _copy_tree(research_src / "phase9_9_best", research_dst / "phase9_9_best")

    for name in _RESEARCH_BUNDLES:
        src = research_src / name
        if not src.is_dir():
            raise FileNotFoundError(f"Required trend bundle missing for kernel tmp fixture: {src}")
        _copy_tree(src, research_dst / name)

    from tradingbot.config.live import PRIMARY_SYMBOL

    candle_store = CandleStore(tmp)
    symbols = ["XAUUSD"]
    if str(PRIMARY_SYMBOL).upper() not in {s.upper() for s in symbols}:
        symbols.append(str(PRIMARY_SYMBOL))
    for symbol in symbols:
        candle_store.store(symbol, "M5", candles)
        if dataset is not None:
            DatasetStore(tmp).store_v2(symbol, "M5", dataset)

    # get_trend_bundle reloads unless _trend_version is set; get_registry sets it.
    PipelineCache.get_registry(base_dir=tmp, symbol="XAUUSD")


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
