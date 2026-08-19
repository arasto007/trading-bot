"""Phase D — gate live ML kernel on shadow metrics (PF when ML agrees > 1.2)."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.ml.shadow.phase_d_metrics import compute_shadow_metrics

logger = logging.getLogger(__name__)


def evaluate_ml_live_gate(*, force: bool = False) -> dict[str, Any]:
    """
    Returns gate verdict. Phase 49A (preferred) or Phase D fallback:
    - Phase 49A: >= 100 closed trades, agree PF>1.2, exp>0.15R, prec buy/sell>60%
    - Phase D legacy: >= 100 closed, PF when ML agrees > 1.2
    """
    from tradingbot.ml.shadow.phase49a_gate import evaluate_ml_kernel_live_ready

    phase49a = evaluate_ml_kernel_live_ready(force=force)
    if int(phase49a.get("sample_size", 0) or 0) > 0:
        return {
            "allowed": bool(phase49a.get("allowed")),
            "gate_version": "phase49a",
            "closed_trades": phase49a.get("sample_size"),
            "pf_ml_agrees": phase49a.get("ml_agrees_with_live", {}).get("pf"),
            "ml_agrees_trades": phase49a.get("ml_agrees_with_live", {}).get("trades"),
            **phase49a,
        }

    metrics = compute_shadow_metrics()
    allowed = bool(metrics.get("ml_live_allowed"))
    if not allowed and not force:
        logger.info(
            "ML live gate CLOSED | closed=%s matched=%s pf_agrees=%s (need n>=%s pf>%s)",
            metrics.get("closed_trades"),
            metrics.get("matched_trades"),
            metrics.get("pf_ml_agrees"),
            metrics.get("min_trades"),
            metrics.get("pf_gate"),
        )
    elif allowed:
        logger.info(
            "ML live gate OPEN | closed=%s pf_agrees=%s",
            metrics.get("closed_trades"),
            metrics.get("pf_ml_agrees"),
        )
    return {
            "allowed": allowed,
            "gate_version": "phase_d",
            **metrics,
        }


def is_ml_live_execution_allowed() -> bool:
    return bool(evaluate_ml_live_gate().get("allowed"))
