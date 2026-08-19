"""Phase 22I — run Dataset A backtest with research orchestrator."""

from __future__ import annotations

import contextlib
from typing import Any

from tradingbot.ml.research.phase22f.config import RapidDataset, configure_research_env
from tradingbot.ml.research.phase22i.candidates import PolicyCandidate
from tradingbot.ml.research.phase22i.stack import simulate_candidate_backtest


@contextlib.contextmanager
def _patched_ml_stack(research_stack):
    import tradingbot.ml.integration.factory as factory

    original = factory.build_ml_kernel_stack
    factory.build_ml_kernel_stack = lambda **kwargs: research_stack
    try:
        yield
    finally:
        factory.build_ml_kernel_stack = original


async def run_candidate_dataset_a(
    candidate: PolicyCandidate,
    dataset: RapidDataset,
    *,
    base_dir: str | None,
    timeframe: str = "M5",
) -> dict[str, Any]:
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest

    configure_research_env()
    stack = simulate_candidate_backtest(candidate, base_dir=base_dir)
    with _patched_ml_stack(stack):
        result = await run_rapid_backtest(timeframe, dataset)
    hc = result.get("hold_chain") or {}
    metrics = result.get("metrics") or {}
    summary = result.get("summary") or {}
    confs = []
    for ev in result.get("blocked_events") or []:
        c = ev.get("confidence")
        if c is not None:
            confs.append(float(c))

    return {
        "candidate_id": candidate.id,
        "title": candidate.title,
        "timeframe": timeframe,
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
        "bars_evaluated": hc.get("bars_evaluated"),
        "decision_hold": (hc.get("ml_hold_stages") or {}).get("decision_hold"),
        "avg_confidence_blocked": round(sum(confs) / len(confs), 4) if confs else None,
        "elapsed_sec": result.get("elapsed_sec"),
    }
