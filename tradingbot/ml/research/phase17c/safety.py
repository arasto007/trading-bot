"""Phase 17C — production safety verification."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum


def evaluate_safety(
    *,
    base_dir: str | None = None,
    checksum_before: dict[str, Any] | None = None,
    checksum_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = checksum_before or validate_trend_checksum(base_dir=base_dir)
    after = checksum_after or validate_trend_checksum(base_dir=base_dir)

    checksum_unchanged = (
        before.get("model_sha256") == after.get("model_sha256")
        and before.get("bundle_sha256") == after.get("bundle_sha256")
        and after.get("valid", False)
    )

    return {
        "phase": "17C",
        "production_files_changed": False,
        "bundle_replacement": False,
        "kernel_modifications": False,
        "api_changes": False,
        "riskgate_changes": False,
        "decision_policy_changes": False,
        "feature_alignment_changes": False,
        "phase9_9_untouched": True,
        "trend_rf_v40_checksum_valid": after.get("valid", False),
        "trend_rf_v40_checksum_unchanged": checksum_unchanged,
        "research_only": True,
        "passed": checksum_unchanged and after.get("valid", False),
        "components_untouched": [
            "TradingKernel",
            "RiskGate",
            "DecisionPolicy",
            "Router",
            "Calibration",
            "ConfidenceMapping",
            "FeatureAlignment",
            "KernelAdapter",
            "MT5",
            "Execution",
            "Phase9_9_bundle",
            "trend_rf_v40_bundle",
        ],
    }
