"""Phase 20A — instant rollback to safe baseline."""

from __future__ import annotations

import os
from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache


def execute_rollback(*, reason: str = "instability") -> dict[str, Any]:
    """
    Immediate rollback:
      TREND_MODEL_VERSION=v40
      ENABLE_RSI_FILTER=false / ENABLE_ADX_FILTER=false
    """
    os.environ["TREND_MODEL_VERSION"] = "v40"
    os.environ["ENABLE_RSI_FILTER"] = "false"
    os.environ["ENABLE_ADX_FILTER"] = "false"
    os.environ["RSI_FILTER"] = "false"
    os.environ["ADX_FILTER"] = "false"
    PipelineCache.reset()

    return {
        "phase": "20A",
        "rollback": True,
        "reason": reason,
        "trend_model_version": "v40",
        "filters_disabled": True,
        "mode": "ROLLBACK_IMMEDIATE",
    }
