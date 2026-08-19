"""Phase 18C — pre-live verification (market closed, no trading)."""

__all__ = ["run_phase18c_prelive"]


def run_phase18c_prelive(*args, **kwargs):
    from tradingbot.ml.phase18c.orchestrator import run_phase18c_prelive as _run

    return _run(*args, **kwargs)
