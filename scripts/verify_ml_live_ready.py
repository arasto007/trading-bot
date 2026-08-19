#!/usr/bin/env python3
"""Check ML model artifacts + USE_ML_KERNEL before live trading."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def _ok(label: str, passed: bool, detail: str = "") -> tuple[bool, str]:
    status = "OK" if passed else "MISSING"
    line = f"{label}|{status}"
    if detail:
        line += f"|{detail}"
    return passed, line


def _load_orchestrator_module():
    import importlib.util

    path = ROOT / "scripts" / "live_dataset_orchestrator.py"
    spec = importlib.util.spec_from_file_location("live_dataset_orchestrator", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load orchestrator from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _dataset_staleness_warning(*, max_lag_hours: float) -> tuple[str | None, dict[str, str | float | None]]:
    """Read-only check: dataset_v2 lag vs live ParquetCache (warn only, never blocks)."""
    mod = _load_orchestrator_module()
    lag_info = mod.measure_dataset_lag()
    threshold = mod.refresh_threshold_hours()
    meta: dict[str, str | float | None] = {
        "dataset_max_utc": lag_info.get("dataset_max_utc"),
        "live_max_utc": lag_info.get("live_max_utc"),
        "lag_hours": lag_info.get("lag_hours"),
        "max_lag_hours": max_lag_hours,
    }
    if not lag_info.get("dataset_exists"):
        return "DATASET_STALE|WARN|dataset_v2 missing", meta
    if lag_info.get("lag_hours") is None:
        return None, meta

    lag_hours = float(lag_info["lag_hours"])
    threshold = mod.refresh_threshold_hours()
    if lag_hours > max_lag_hours:
        auto = "watchdog will auto-refresh before live" if lag_hours > threshold else ""
        suffix = f" — {auto}" if auto else ""
        return (
            f"DATASET_STALE|WARN|lag {round(lag_hours, 1)}h > {max_lag_hours}h{suffix}",
            meta,
        )
    return f"DATASET_FRESH|OK|lag {round(lag_hours, 1)}h", meta


def main() -> int:
    from tradingbot.ml.integration.config import is_ml_kernel_enabled
    from tradingbot.ml.phase15a.config import trend_rf_model_path
    from tradingbot.ml.data.paths import phase9_9_model_path
    from tradingbot.services.meta_labeler import MODEL_DIR

    lines: list[str] = []
    all_ok = True

    ml_on = is_ml_kernel_enabled()
    _, line = _ok("ML_KERNEL", True, "ON" if ml_on else "OFF")
    lines.append(line)

    trend_pkl = trend_rf_model_path(None, version="v41")
    p99_pkl = phase9_9_model_path(None)
    meta_m15 = MODEL_DIR / "meta_labeler_m15.pkl"

    checks = [
        ("TREND_V41", trend_pkl.is_file(), str(trend_pkl.name)),
        ("RANGE_P99", p99_pkl.is_file(), str(p99_pkl.name)),
        ("META_M15", meta_m15.is_file(), str(meta_m15.name)),
    ]
    for label, exists, name in checks:
        passed, line = _ok(label, exists, name)
        lines.append(line)
        if not exists:
            all_ok = False

    if ml_on and not all_ok:
        lines.append("VERDICT|NOT_READY|enable ML but model files missing")
        print("\n".join(lines))
        return 1

    if ml_on:
        import os

        max_lag = float(os.environ.get("ML_DATASET_MAX_LAG_HOURS", "48"))
        stale_line, _ = _dataset_staleness_warning(max_lag_hours=max_lag)
        if stale_line:
            lines.append(stale_line)

    if ml_on and all_ok:
        try:
            from tradingbot.adapters.legacy_loader import load_legacy_config
            from tradingbot.ml.integration.factory import build_strategy_registry
            from tradingbot.ml.integration.health_gate import run_pre_decision_health
            from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry
            from tradingbot.ml.integration.pipeline_cache import PipelineCache

            legacy_cfg = load_legacy_config()
            live_base = legacy_cfg.get("BASE_DIR")
            registry = PipelineCache.get_registry(base_dir=live_base)
            health = run_pre_decision_health(registry=registry, base_dir=live_base)
            hg_ok = health.passes
            lines.append(f"HEALTH_GATE|{'OK' if hg_ok else 'FAIL'}")
            if not hg_ok:
                all_ok = False
                lines.append(f"VERDICT|NOT_READY|{';'.join(health.errors[:3])}")
            else:
                strat_reg = build_strategy_registry(
                    legacy_cfg, base_dir=live_base,
                )
                if not isinstance(strat_reg, MLKernelRegistry):
                    all_ok = False
                    lines.append("LIVE_REGISTRY|FAIL|expected MLKernelRegistry")
                    lines.append("VERDICT|NOT_READY|strategy registry not ML")
                else:
                    lines.append("LIVE_REGISTRY|OK|MLKernelRegistry")
                    lines.append("VERDICT|READY|ML stack OK")
        except Exception as e:
            all_ok = False
            lines.append(f"HEALTH_GATE|FAIL|{e}")
            lines.append("VERDICT|NOT_READY|health check error")
    elif not ml_on:
        lines.append("VERDICT|LEGACY|Price Action only (USE_ML_KERNEL=false)")
    else:
        lines.append("VERDICT|PARTIAL|some artifacts missing")

    print("\n".join(lines))
    return 0 if all_ok or not ml_on else 1


if __name__ == "__main__":
    raise SystemExit(main())
