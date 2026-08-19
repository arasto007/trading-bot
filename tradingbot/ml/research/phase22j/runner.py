"""Phase 22J — run Dataset A backtest with engine candidate patch."""

from __future__ import annotations

import contextlib
from typing import Any

from tradingbot.ml.integration.factory import MLKernelStack, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.research.phase22f.config import RapidDataset, configure_research_env
from tradingbot.ml.research.phase22j.engine_candidates import EngineCandidate


@contextlib.contextmanager
def _patched_stack(research_stack: MLKernelStack):
    import tradingbot.ml.integration.factory as factory

    original = factory.build_ml_kernel_stack
    factory.build_ml_kernel_stack = lambda **kwargs: research_stack
    try:
        yield
    finally:
        factory.build_ml_kernel_stack = original
        PipelineCache.reset()


def build_stack_with_candidate(candidate: EngineCandidate, *, base_dir: str | None) -> MLKernelStack:
    configure_research_env()
    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir)
    candidate.apply(registry=stack.registry, base_dir=base_dir)
    return stack


async def run_engine_candidate(dataset: RapidDataset, candidate: EngineCandidate, *, base_dir: str | None) -> dict[str, Any]:
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest

    stack = build_stack_with_candidate(candidate, base_dir=base_dir)
    with _patched_stack(stack):
        result = await run_rapid_backtest("M5", dataset)
    hc = result.get("hold_chain") or {}
    metrics = result.get("metrics") or {}
    summary = result.get("summary") or {}
    return {
        "candidate_id": candidate.id,
        "title": candidate.title,
        "trades": result.get("trades"),
        "buy_pct": summary.get("buy_pct"),
        "sell_pct": summary.get("sell_pct"),
        "hold_pct": summary.get("hold_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "expectancy": metrics.get("expectancy"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "buy_emitted": hc.get("buy_emitted"),
        "sell_emitted": hc.get("sell_emitted"),
        "decision_hold": (hc.get("ml_hold_stages") or {}).get("decision_hold"),
        "elapsed_sec": result.get("elapsed_sec"),
        "error": result.get("error"),
    }
