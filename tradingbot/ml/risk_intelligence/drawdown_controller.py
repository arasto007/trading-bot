"""Phase 14.2B — equity drawdown protection."""

from __future__ import annotations

from tradingbot.ml.risk_intelligence.risk_policy import BLOCK_DRAWDOWN_PERCENT


def drawdown_risk_multiplier(drawdown_pct: float) -> tuple[float, str, bool]:
    dd = float(drawdown_pct)
    if dd >= BLOCK_DRAWDOWN_PERCENT:
        return 0.0, f"drawdown {dd:.1f}% ≥ {BLOCK_DRAWDOWN_PERCENT}% — block", True
    if dd < 3.0:
        return 1.0, "drawdown 0-3% normal", False
    if dd < 5.0:
        return 0.75, "drawdown 3-5% ×0.75", False
    if dd < 8.0:
        return 0.50, "drawdown 5-8% ×0.5", False
    return 0.0, "drawdown protection block", True
