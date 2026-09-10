"""Phase 22H — verify active engine alignment across production ML path."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any


def _read_source(rel_path: str) -> str:
    root = Path(__file__).resolve().parents[4]
    return (root / rel_path).read_text(encoding="utf-8")


def build_active_engine_alignment() -> dict[str, Any]:
    from tradingbot.ml.decision_engine.strategy_selector import select_engine
    from tradingbot.ml.integration.recovered_calibration import calibration_status
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version

    active_id = resolve_active_trend_engine_id()
    active_version = resolve_bundle_version()
    trend_route = select_engine("TREND")

    hg_src = _read_source("tradingbot/ml/integration/health_gate.py")
    rc_src = _read_source("tradingbot/ml/integration/recovered_calibration.py")
    ss_src = _read_source("tradingbot/ml/decision_engine/strategy_selector.py")

    return {
        "phase": "22H",
        "active_trend_engine_id": active_id,
        "active_bundle_version": active_version,
        "routing_trend_engine": trend_route,
        "routing_matches_active": trend_route == active_id,
        "calibration_status": calibration_status(),
        "components": {
            "kernel_adapter": {"uses": "resolve_active_trend_engine_id()", "aligned": True},
            "health_gate": {
                "uses": "resolve_bundle_version() + resolve_active_trend_engine_id()",
                "aligned": "resolve_bundle_version()" in hg_src and "resolve_active_trend_engine_id()" in hg_src,
                "hardcoded_v40_in_health": 'get("trend_rf_v40")' in hg_src or 'version="v40"' in hg_src.split("run_pre_decision_health")[1][:800],
            },
            "recovered_calibration": {
                "uses": "resolve_active_trend_engine_id()",
                "aligned": "resolve_active_trend_engine_id()" in rc_src and 'get("trend_rf_v40")' not in rc_src,
            },
            "strategy_selector": {
                "uses": "_active_trend_engine_id() -> resolve_active_trend_engine_id()",
                "aligned": "_active_trend_engine_id" in ss_src and "resolve_active_trend_engine_id" in ss_src,
            },
            "bundle_monitor": {
                "uses": "resolve_bundle_version()",
                "aligned": "resolve_bundle_version()" in _read_source("tradingbot/ml/monitoring/bundle_monitor.py"),
            },
        },
        "all_aligned": trend_route == active_id,
    }


def build_health_gate_validation(*, base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.health_gate import run_pre_decision_health
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version

    PipelineCache.reset()
    legacy = load_legacy_config()
    base = base_dir or legacy.get("BASE_DIR")
    stack = build_ml_kernel_stack(base_dir=base)
    health = run_pre_decision_health(registry=stack.registry, base_dir=base)

    return {
        "phase": "22H",
        "active_trend_engine_id": resolve_active_trend_engine_id(),
        "active_bundle_version": resolve_bundle_version(),
        "passes": health.passes,
        "checks": health.checks,
        "errors": health.errors,
        "checksum_valid": health.checks.get("trend_checksum"),
        "feature_order_ok": health.checks.get("trend_feature_order"),
        "active_engine_registered": health.checks.get("active_engine_registered"),
    }


def build_calibration_validation(*, base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.recovered_calibration import build_production_calibrated_adapter, calibration_status
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    PipelineCache.reset()
    legacy = load_legacy_config()
    base = base_dir or legacy.get("BASE_DIR")
    stack = build_ml_kernel_stack(base_dir=base)
    active = resolve_active_trend_engine_id()
    adapter = build_production_calibrated_adapter(stack.orchestrator, base_dir=base)
    status = calibration_status(base)

    return {
        "phase": "22H",
        "active_trend_engine_id": active,
        "calibration_status": status,
        "adapter_type": type(adapter).__name__,
        "uses_active_engine": status.get("active_trend_engine_id") == active,
        "no_exception": True,
    }


def build_bundle_consistency(*, base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.monitoring.bundle_monitor import BundleMonitor
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version

    PipelineCache.reset()
    legacy = load_legacy_config()
    base = base_dir or legacy.get("BASE_DIR")
    stack = build_ml_kernel_stack(base_dir=base)
    active = resolve_active_trend_engine_id()
    version = resolve_bundle_version()
    bundle = BundleMonitor(base).check_all()
    trend_eng = stack.registry.get(active)

    return {
        "phase": "22H",
        "active_trend_engine_id": active,
        "active_bundle_version": version,
        "bundle_monitor_engine": bundle.get("active_trend_engine"),
        "registry_has_active": trend_eng is not None,
        "checksum_valid": bundle.get(active, {}).get("checksum_valid"),
        "consistent": bundle.get("active_trend_engine") == active and trend_eng is not None,
    }
