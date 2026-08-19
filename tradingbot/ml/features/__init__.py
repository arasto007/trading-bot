"""Machine learning feature engineering package."""

from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.features.registry import all_features, feature_names, validate_integrity
from tradingbot.ml.features.store import FeatureStore

# Import families to register feature metadata
from tradingbot.ml.features import (  # noqa: F401
    context,
    microstructure,
    momentum,
    price_action,
    session,
    smc,
    trend,
    volatility,
)

__all__ = [
    "FeatureBuilder",
    "FeatureStore",
    "all_features",
    "feature_names",
    "validate_integrity",
]
