"""Phase 17C — stability: latency, determinism, checksum, feature consistency."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle, validate_trend_checksum
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.phase17b.config import TOP5_FEATURES
from tradingbot.ml.research.phase17c.config import MAX_LATENCY_MEDIAN_MS


def evaluate_stability(
    research: ResearchRfModel,
    bundle: TrendRfBundle,
    samples: pd.DataFrame,
    shadow_comparison: dict[str, Any],
    *,
    base_dir: str | None = None,
) -> dict[str, Any]:
    # Determinism: same row → same probability (3 runs).
    if samples.empty:
        det_ok = True
        det_probs = []
    else:
        row = samples.iloc[0]
        det_probs = [research.predict_proba(row) for _ in range(3)]
        det_ok = all(abs(det_probs[0] - p) < 1e-12 for p in det_probs)

    # Feature consistency: all top5 present in research feature_order.
    feature_ok = all(f in research.feature_order for f in TOP5_FEATURES)

    # Bundle checksum (production must remain valid).
    checksum = validate_trend_checksum(base_dir=base_dir)

    # Latency from 365d window.
    win365 = shadow_comparison.get("windows", {}).get("365d", {})
    frozen_lat = win365.get("frozen", {}).get("latency", {})
    research_lat = win365.get("research", {}).get("latency", {})
    latency_ok = (
        research_lat.get("median", 999) <= MAX_LATENCY_MEDIAN_MS
        or research_lat.get("p95_ms", 999) <= 250.0
    )

    # Memory/CPU proxies: feature count and model size indicators (no psutil required).
    memory_proxy = {
        "research_feature_count": len(research.feature_order),
        "frozen_feature_count": len(bundle.feature_order),
        "research_n_estimators": getattr(research.model, "n_estimators", None),
        "note": "proxy_only_no_process_sampling",
    }

    return {
        "phase": "17C",
        "prediction_determinism": {
            "passed": det_ok,
            "sample_probs": [round(float(p), 8) for p in det_probs],
        },
        "feature_consistency": {
            "passed": feature_ok,
            "top5_present": {f: f in research.feature_order for f in TOP5_FEATURES},
        },
        "bundle_checksum": {
            "production_valid": checksum.get("valid", False),
            "details": checksum,
        },
        "latency": {
            "frozen": frozen_lat,
            "research": research_lat,
            "acceptable": latency_ok,
        },
        "memory_cpu_proxy": memory_proxy,
        "passed": det_ok and feature_ok and checksum.get("valid", False) and latency_ok,
    }
