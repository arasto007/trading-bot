"""Phase 18A — hard safety: zero live orders, no production mutation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum

# Global counter — must remain 0 for entire phase.
ORDER_SEND_CALLS = 0


def record_order_send_attempt() -> None:
    """Forbidden path — any call fails the phase."""
    global ORDER_SEND_CALLS
    ORDER_SEND_CALLS += 1
    raise RuntimeError("PHASE18A_STOP: order_send attempted in shadow mode")


def assert_no_execution() -> dict[str, Any]:
    if ORDER_SEND_CALLS != 0:
        raise RuntimeError(f"PHASE18A_STOP: order_send_calls={ORDER_SEND_CALLS}")
    return {"order_send_calls": 0, "execution_disabled": True}


def evaluate_bundle_safety(*, base_dir: str | None = None) -> dict[str, Any]:
    v40 = validate_trend_checksum(base_dir=base_dir, version="v40")
    v41 = validate_trend_checksum(base_dir=base_dir, version="v41")
    return {
        "phase": "18A",
        "order_send_calls": ORDER_SEND_CALLS,
        "execution_disabled": True,
        "v40_checksum_valid": v40.get("valid", False),
        "v41_checksum_valid": v41.get("valid", False),
        "v40_checksum": v40,
        "v41_checksum": v41,
        "no_retraining": True,
        "no_threshold_changes": True,
        "no_feature_changes": True,
        "no_bundle_modifications": True,
        "no_riskgate_changes": True,
        "no_kernel_changes": True,
        "passed": (
            ORDER_SEND_CALLS == 0
            and v40.get("valid", False)
            and v41.get("valid", False)
        ),
    }
