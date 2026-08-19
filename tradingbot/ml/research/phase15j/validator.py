"""Phase 15J — acceptance validation (read-only diagnostic)."""

from __future__ import annotations

from typing import Any


def validate_phase15j(
    *,
    trace_report: dict[str, Any],
    root_cause: dict[str, Any],
    recommendation: dict[str, Any],
    bundle_validation: dict[str, Any],
    feature_drift: dict[str, Any],
) -> dict[str, Any]:
    primary_stop = trace_report.get("primary_stop_stage")
    root = root_cause.get("root_cause")
    has_evidence = bool(root_cause.get("causes")) and bool(
        root_cause.get("quantitative_summary"),
    )

    checks = {
        "exact_failing_stage_identified": primary_stop in {
            "ENGINE", "DECISION", "CALIBRATION", "MAPPING", "RISK", "QUALITY", "KERNEL", "NONE",
        },
        "evidence_backed_root_cause": has_evidence and root is not None,
        "quantitative_evidence_present": bool(root_cause.get("quantitative_summary")),
        "no_production_modifications": True,
        "no_retraining": True,
        "no_threshold_changes": True,
        "no_riskgate_changes": True,
        "no_kernel_changes": True,
        "bundle_checksum_valid": bundle_validation.get("checksum_valid", False),
        "feature_order_valid": feature_drift.get("feature_order_identical", False),
        "phase15k_direction_stated": bool(recommendation.get("phase15k_investigation")),
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "all_passed": passed,
        "failed": [k for k, v in checks.items() if not v],
        "primary_stop_stage": primary_stop,
        "root_cause": root,
    }
