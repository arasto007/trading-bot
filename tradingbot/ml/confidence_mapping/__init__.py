"""Phase 15H — confidence scale mapping for frozen bundle production."""

from tradingbot.ml.confidence_mapping.config import (
    DEFAULT_DAYS,
    DEFAULT_SEED,
    MAX_LATENCY_INCREASE,
    PARITY_TARGET,
    reports_dir,
)
from tradingbot.ml.confidence_mapping.confidence_mapper import ConfidenceMapper
from tradingbot.ml.confidence_mapping.production_adapter import (
    MappedProductionRiskAdapter,
    build_confidence_mapper,
    build_mapped_production_risk,
)


def run_phase15h_mapping(*args, **kwargs):
    from tradingbot.ml.confidence_mapping.orchestrator import run_phase15h_mapping as _run
    return _run(*args, **kwargs)


__all__ = [
    "ConfidenceMapper",
    "DEFAULT_DAYS",
    "DEFAULT_SEED",
    "MAX_LATENCY_INCREASE",
    "MappedProductionRiskAdapter",
    "PARITY_TARGET",
    "build_confidence_mapper",
    "build_mapped_production_risk",
    "reports_dir",
    "run_phase15h_mapping",
]
