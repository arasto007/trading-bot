"""Phase 49A — ML Kernel shadow validation gate (stricter than Phase D)."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.ml.shadow.phase49a_metrics import compute_phase49a_metrics

logger = logging.getLogger(__name__)


def evaluate_ml_kernel_live_ready(*, force: bool = False) -> dict[str, Any]:
    """
    ML kernel live allowed only when Phase 49A criteria pass on closed trades:
    - sample >= 100
    - ML agree PF > 1.2, expectancy > 0.15R
    - precision_buy & precision_sell > 60%
    """
    metrics = compute_phase49a_metrics()
    ready = bool(metrics.get("ml_kernel_live_ready"))
    if not ready and not force:
        logger.info(
            "ML kernel live gate CLOSED | sample=%s agree_pf=%s agree_exp=%s "
            "prec_buy=%s prec_sell=%s (need n>=%s)",
            metrics.get("sample_size"),
            metrics.get("ml_agrees_with_live", {}).get("pf"),
            metrics.get("ml_agrees_with_live", {}).get("expectancy_r"),
            metrics.get("precision_buy_pct"),
            metrics.get("precision_sell_pct"),
            metrics.get("min_sample"),
        )
    elif ready:
        logger.info(
            "ML kernel live gate OPEN | sample=%s agree_pf=%s",
            metrics.get("sample_size"),
            metrics.get("ml_agrees_with_live", {}).get("pf"),
        )
    return {"allowed": ready, "ml_kernel_live_ready": ready, **metrics}


def is_ml_kernel_live_ready() -> bool:
    return bool(evaluate_ml_kernel_live_ready().get("allowed"))
