"""Phase 53A — ML kernel live gate (Phase 51 real-trade evidence)."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.ml.shadow.phase53a_metrics import compute_phase53a_metrics

logger = logging.getLogger(__name__)


def evaluate_ml_kernel_phase53a(*, force: bool = False) -> dict[str, Any]:
    """
    ML kernel live allowed when Phase 53A criteria pass on Phase 51 closed trades:
    - sample >= 100 from forward demo
    - ML agree PF > 1.2, expectancy > 0.15R
    - precision_buy & precision_sell > 60%
    - ML disagree PF < overall live PF
    """
    metrics = compute_phase53a_metrics()
    ready = bool(metrics.get("ml_kernel_live_ready"))
    if not ready and not force:
        logger.info(
            "Phase53A ML kernel gate CLOSED | sample=%s/%s agree_pf=%s agree_exp=%s "
            "prec_buy=%s prec_sell=%s disagree_pf=%s live_pf=%s",
            metrics.get("sample_size"),
            metrics.get("min_sample"),
            metrics.get("ml_agrees_with_live", {}).get("pf"),
            metrics.get("ml_agrees_with_live", {}).get("expectancy_r"),
            metrics.get("precision_buy_pct"),
            metrics.get("precision_sell_pct"),
            metrics.get("ml_disagrees_with_live", {}).get("pf"),
            metrics.get("live_pf"),
        )
    elif ready:
        logger.info(
            "Phase53A ML kernel gate OPEN | sample=%s agree_pf=%s",
            metrics.get("sample_size"),
            metrics.get("ml_agrees_with_live", {}).get("pf"),
        )
    return {"allowed": ready, **metrics}


def is_ml_kernel_live_ready_phase53a() -> bool:
    return bool(evaluate_ml_kernel_phase53a().get("allowed"))
