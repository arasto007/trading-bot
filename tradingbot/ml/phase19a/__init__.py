"""Phase 19A — profitability audit (read-only)."""

__all__ = ["run_phase19a_audit"]


def run_phase19a_audit(*args, **kwargs):
    from tradingbot.ml.phase19a.orchestrator import run_phase19a_audit as _run

    return _run(*args, **kwargs)
