"""Phase 19B — profitability optimization (research only)."""

__all__ = ["run_phase19b_optimization"]


def run_phase19b_optimization(*args, **kwargs):
    from tradingbot.ml.research.phase19b.orchestrator import run_phase19b_optimization as _run

    return _run(*args, **kwargs)
