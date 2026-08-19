"""Phase 17D — production bundle promotion (safe deployment)."""

__all__ = ["run_phase17d_promotion"]


def run_phase17d_promotion(*args, **kwargs):
    from tradingbot.ml.phase17d.orchestrator import run_phase17d_promotion as _run

    return _run(*args, **kwargs)
