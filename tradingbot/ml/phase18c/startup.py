"""Phase 18C — startup simulation (no trading)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache


def validate_startup(
    *,
    project_root: Path,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    exceptions: list[str] = []

    def _step(name: str, fn) -> None:
        try:
            detail = fn()
            steps.append({"step": name, "status": "PASS", "detail": detail})
        except Exception as exc:  # noqa: BLE001
            exceptions.append(f"{name}: {exc}")
            steps.append({"step": name, "status": "FAIL", "error": str(exc)})

    def init_order():
        return {"order": ["cache_reset", "registry", "stack", "adapter", "health", "monitoring"]}

    def cache_loading():
        PipelineCache.reset()
        reg = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
        return {"ids": reg.list_ids()}

    def bundle_loading():
        from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
        from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
        v40 = load_trend_bundle(base_dir=base_dir, version="v40")
        v41 = load_trend_bundle(base_dir=base_dir, version="v41")
        p99 = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
        return {
            "v40_features": len(v40.feature_order),
            "v41_features": len(v41.feature_order),
            "phase9_9": p99 is not None,
        }

    def dependency_injection():
        from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
        PipelineCache.reset()
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
        return {"stack": type(stack).__name__, "adapter": type(adapter).__name__}

    def health_checks():
        from tradingbot.ml.phase15a.health_check import run_health_checks
        return run_health_checks(base_dir=base_dir)

    def monitoring():
        mon = project_root / "tradingbot/ml/monitoring"
        return {"present": mon.is_dir(), "modules": [p.name for p in mon.glob("*.py")][:10] if mon.is_dir() else []}

    def log_creation():
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        probe = log_dir / "phase18c_startup.log"
        probe.write_text("phase18c startup ok\n", encoding="utf-8")
        return {"log": str(probe), "exists": probe.is_file()}

    _step("initialization_order", init_order)
    _step("cache_loading", cache_loading)
    _step("bundle_loading", bundle_loading)
    _step("dependency_injection", dependency_injection)
    _step("health_checks", health_checks)
    _step("monitoring", monitoring)
    _step("log_creation", log_creation)

    passed = len(exceptions) == 0 and all(s["status"] == "PASS" for s in steps)
    return {
        "phase": "18C",
        "passed": passed,
        "steps": steps,
        "exceptions": exceptions,
        "no_exceptions": len(exceptions) == 0,
    }
