"""Phase 14.4 — robustness scoring."""

from __future__ import annotations

from typing import Any

import numpy as np


def robustness_score(metrics: dict[str, Any], *, walk_forward_score: float = 0.5) -> float:
    trades = int(metrics.get("trades", 0))
    if trades < 300:
        return 0.0
    pf = min(float(metrics.get("profit_factor", 0.0)), 3.0) / 3.0
    exp = min(max(float(metrics.get("expectancy", 0.0)) + 1.0, 0.0), 2.0) / 2.0
    dd = 1.0 - min(float(metrics.get("max_drawdown", 1.0)), 1.0)
    wf = min(max(float(walk_forward_score), 0.0), 1.0)
    consistency = min(trades / 500.0, 1.0)
    return round(pf * 0.25 + exp * 0.20 + wf * 0.30 + consistency * 0.15 + dd * 0.10, 4)


def pf_stability(pfs: list[float]) -> float:
    if not pfs:
        return 0.0
    if len(pfs) == 1:
        return 0.5
    return round(max(0.0, 1.0 - float(np.std(pfs))), 4)
