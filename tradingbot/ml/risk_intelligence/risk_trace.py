"""Phase 14.2B — explainable risk trace."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.risk_intelligence.risk_types import AdaptiveRiskContext, RiskRecommendation


def risk_intelligence_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "risk_intelligence"


def build_risk_trace(
    ctx: AdaptiveRiskContext,
    recommendation: RiskRecommendation,
) -> dict[str, Any]:
    return {
        "symbol": ctx.market.symbol,
        "action": ctx.action,
        "engine": ctx.engine,
        "regime": ctx.regime,
        "calibrated_confidence": round(ctx.calibrated_confidence, 6),
        "atr_percentile": round(ctx.atr_percentile, 4),
        "session": ctx.session,
        "drawdown_pct": round(ctx.account.drawdown_pct, 4),
        "recommendation": recommendation.to_dict(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_risk_traces(traces: list[dict[str, Any]], *, base_dir: str | Path | None = None) -> Path:
    out = risk_intelligence_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "risk_traces.json"
    path.write_text(json.dumps(traces[-500:], indent=2), encoding="utf-8")
    return path
