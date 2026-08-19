"""Phase 17D — deployment verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase17d.config import VERDICTS


def build_checks(
    *,
    bundle_manifest: dict[str, Any],
    health: dict[str, Any],
    registry: dict[str, Any],
    rollback: dict[str, Any],
    compatibility: dict[str, Any],
    live_safety: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, bool]:
    return {
        "bundle_validated": bundle_manifest.get("checksum", {}).get("bundle_sha256") is not None,
        "registry_updated": registry.get("both_versions_registered", False),
        "rollback_works": rollback.get("passed", False),
        "checksums_valid": (
            health.get("v40_bundle", {}).get("checksum_valid", False)
            and health.get("v41_bundle", {}).get("checksum_valid", False)
        ),
        "range_unchanged": compatibility.get("comparison", {}).get("range_identical_v40_v41", False),
        "trend_equals_phase17c": compatibility.get("passed", False),
        "no_regressions": regression.get("passed", False),
        "production_pipeline_healthy": health.get("passed", False),
        "v40_untouched": live_safety.get("v40_checksum_unchanged", False),
        "live_safety_passed": live_safety.get("passed", False),
    }


def determine_verdict(checks: dict[str, bool]) -> str:
    required = (
        "bundle_validated",
        "registry_updated",
        "rollback_works",
        "checksums_valid",
        "range_unchanged",
        "trend_equals_phase17c",
        "no_regressions",
        "production_pipeline_healthy",
    )
    if all(checks.get(k, False) for k in required):
        return "READY_FOR_LIVE_SHADOW"
    return "DEPLOYMENT_BLOCKED"


def build_final_report(
    *,
    verdict: str,
    checks: dict[str, bool],
    bundle_manifest: dict[str, Any],
    health: dict[str, Any],
    registry: dict[str, Any],
    rollback: dict[str, Any],
    compatibility: dict[str, Any],
    live_safety: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    checks_passed = sum(1 for v in checks.values() if v)
    return {
        "phase": "17D",
        "verdict": verdict,
        "checks": checks,
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "verdicts_allowed": list(VERDICTS),
        "bundle_version": bundle_manifest.get("bundle_version"),
        "active_engine": registry.get("active_engine_id"),
        "summary": {
            "trend_actionable_v41": compatibility.get("comparison", {}).get("trend_actionable_v41"),
            "trend_actionable_v40": compatibility.get("comparison", {}).get("trend_actionable_v40"),
            "range_identical": checks.get("range_unchanged"),
            "rollback_instant": checks.get("rollback_works"),
            "regression_passed": regression.get("tests_passed"),
        },
        "deployment": {
            "bundle_promoted": verdict == "READY_FOR_LIVE_SHADOW",
            "rollback_env": "TREND_MODEL_VERSION",
            "default_active": "v41",
        },
    }
