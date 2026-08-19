"""Phase 22G — baseline runner for bottleneck analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase22f.config import RapidDataset
from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest


async def run_baseline_for_bottleneck(dataset: RapidDataset) -> dict[str, Any]:
    out: dict[str, Any] = {"dataset": dataset.to_dict(), "per_tf": {}}
    for tf in ("M5", "M15", "H4"):
        try:
            out["per_tf"][tf] = await run_rapid_backtest(tf, dataset)
        except Exception as exc:
            out["per_tf"][tf] = {"error": str(exc), "timeframe": tf}
    return out
