"""Phase 13.4 — ML probability filter for Phase 13.3 trend signals."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS

DEFAULT_THRESHOLD = 0.55
MODEL_VERSION_PREFIX = "phase13_4_trend_ml"


def apply_trend_ml_filter(
    row: pd.Series | dict[str, Any],
    *,
    model: Any,
    scaler: Any,
    model_name: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    if isinstance(row, dict):
        row = pd.Series(row)

    cols = [c for c in TREND_ML_FEATURE_COLUMNS if c in row.index]
    X = pd.DataFrame([row[cols].astype(np.float64).values], columns=cols)
    X_s = scaler.transform(X)
    proba = float(model.predict_proba(X_s)[0, 1])
    allow = proba >= threshold
    confidence = min(1.0, max(0.0, abs(proba - 0.5) * 2.0))

    return {
        "probability": round(proba, 4),
        "confidence": round(confidence, 4),
        "allow_trade": bool(allow),
        "model_version": f"{MODEL_VERSION_PREFIX}_{model_name}",
        "threshold": threshold,
    }
