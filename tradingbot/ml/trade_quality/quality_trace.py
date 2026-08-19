"""Phase 14.3 — explainable quality traces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.trade_quality.quality_types import QualityScore, TradeQualityContext


def trade_quality_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "trade_quality"


def build_quality_trace(ctx: TradeQualityContext, score: QualityScore) -> dict[str, Any]:
    return {
        "context": ctx.to_dict(),
        "quality": score.to_dict(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_quality_traces(traces: list[dict[str, Any]], *, base_dir: str | Path | None = None) -> Path:
    out = trade_quality_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "quality_traces.json"
    path.write_text(json.dumps(traces[-500:], indent=2), encoding="utf-8")
    return path
