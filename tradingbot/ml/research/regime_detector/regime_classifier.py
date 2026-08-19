"""Phase 13.2 — rule baseline and ML regime classifiers (research only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.regime_detector.regime_features import REGIME_FEATURE_COLUMNS

REGIME_LABELS: tuple[str, ...] = ("RANGE", "TREND", "HIGH_VOLATILITY", "NO_TRADE")

ADX_TREND_MIN = 25.0
ADX_RANGE_MAX = 20.0
ATR_HIGH_VOL = 90.0
ATR_EXTREME = 95.0
ATR_LOW_VOL = 30.0
EMA_SLOPE_STRONG = 0.15
SPREAD_ABNORMAL = 8.0


def rule_classify_row(row: pd.Series | dict[str, Any]) -> str:
    """Baseline rule engine per Phase 13.2 spec."""
    if isinstance(row, dict):
        row = pd.Series(row)

    spread = float(row.get("spread_pips", 0.0))
    atr_pct = float(row.get("atr_percentile", 50.0))
    adx = float(row.get("adx", row.get("trend_strength", 0.0)))
    ema50_slope = float(row.get("ema50_slope", 0.0))
    volatility = float(row.get("volatility", 0.0))

    if spread >= SPREAD_ABNORMAL or atr_pct >= ATR_EXTREME or volatility >= 5.0:
        return "NO_TRADE"
    if atr_pct > ATR_HIGH_VOL:
        return "HIGH_VOLATILITY"
    if adx > ADX_TREND_MIN and abs(ema50_slope) >= EMA_SLOPE_STRONG:
        return "TREND"
    if adx < ADX_RANGE_MAX and atr_pct < ATR_LOW_VOL:
        return "RANGE"
    if adx > ADX_TREND_MIN:
        return "TREND"
    return "RANGE"


def rule_classify(features: pd.DataFrame | pd.Series) -> pd.Series | str:
    if isinstance(features, pd.Series):
        return rule_classify_row(features)
    return features.apply(rule_classify_row, axis=1)


def encode_labels(labels: pd.Series) -> np.ndarray:
    mapping = {name: i for i, name in enumerate(REGIME_LABELS)}
    return labels.map(lambda x: mapping.get(str(x), mapping["RANGE"])).astype(int).to_numpy()


def decode_labels(encoded: np.ndarray) -> list[str]:
    return [REGIME_LABELS[int(i) % len(REGIME_LABELS)] for i in encoded]


def create_ml_model(name: str, *, seed: int = 42) -> Any:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    if name == "logistic":
        return LogisticRegression(max_iter=500, random_state=seed)
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10
        )
    if name == "lightgbm":
        try:
            from lightgbm import LGBMClassifier

            return LGBMClassifier(
                n_estimators=120,
                max_depth=5,
                learning_rate=0.05,
                random_state=seed,
                verbose=-1,
            )
        except ImportError:
            return RandomForestClassifier(n_estimators=80, max_depth=5, random_state=seed)
    raise ValueError(f"Unknown model: {name}")


def available_ml_candidates() -> list[str]:
    candidates = ["logistic", "random_forest"]
    try:
        import lightgbm  # noqa: F401

        candidates.append("lightgbm")
    except ImportError:
        pass
    return candidates
