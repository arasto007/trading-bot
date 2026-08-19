"""Phase 18B — controlled live gate (final GO/NO-GO)."""

__all__ = ["run_phase18b_go_live"]


def run_phase18b_go_live(*args, **kwargs):
    from tradingbot.ml.phase18b.orchestrator import run_phase18b_go_live as _run

    return _run(*args, **kwargs)
