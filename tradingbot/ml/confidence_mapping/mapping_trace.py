"""Phase 15H — mapping trace helpers."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.confidence_mapping.mapping_types import MappingTrace


def build_mapping_trace(
    *,
    frozen: float,
    mapped: float,
    stage: str = "pre_risk",
    **metadata: Any,
) -> dict[str, Any]:
    trace = MappingTrace(frozen=frozen, mapped=mapped, stage=stage, metadata=metadata)
    return trace.to_dict()
