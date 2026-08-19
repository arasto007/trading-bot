"""Phase 18A — live shadow validation (read-only, zero live orders)."""

__all__ = ["run_phase18a_shadow_validation"]


def run_phase18a_shadow_validation(*args, **kwargs):
    from tradingbot.ml.research.phase18a.orchestrator import run_phase18a_shadow_validation as _run

    return _run(*args, **kwargs)
