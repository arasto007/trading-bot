"""Phase 22G — model routing verification from code."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def build_model_routing_verification() -> dict[str, Any]:
    from tradingbot.config.dotenv_loader import load_dotenv

    load_dotenv()

    from tradingbot.ml.integration.config import is_ml_kernel_enabled
    from tradingbot.ml.phase15a.config import (
        RANGE_ENGINE_ID,
        TREND_ENGINE_ID,
        TREND_ENGINE_V41_ID,
        trend_rf_bundle_root,
    )
    from tradingbot.ml.phase17d.config import read_trend_model_version, TREND_VERSION_ENV
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version
    from tradingbot.ml.data.paths import phase9_9_model_path, normalize_ml_base_dir

    base = normalize_ml_base_dir(None)
    version = read_trend_model_version()
    active_id = resolve_active_trend_engine_id()

    v40_root = trend_rf_bundle_root(base, version="v40")
    v41_root = trend_rf_bundle_root(base, version="v41")

    def _artifacts(root: Path) -> dict[str, bool]:
        names = ("model.pkl", "scaler.pkl", "feature_order.json", "checksum.sha256")
        return {n: (root / n).is_file() for n in names}

    env_raw = os.environ.get(TREND_VERSION_ENV)

    return {
        "phase": "22G",
        "verified_from": "source_code",
        "env": {
            TREND_VERSION_ENV: env_raw,
            "USE_ML_KERNEL": os.environ.get("USE_ML_KERNEL"),
            "PHASE22C_ENABLED": os.environ.get("PHASE22C_ENABLED"),
            "is_ml_kernel_enabled": is_ml_kernel_enabled(),
        },
        "trend_routing": {
            "read_function": "tradingbot/ml/phase17d/config.py:read_trend_model_version",
            "resolve_function": "tradingbot/ml/phase17d/versioning.py:resolve_active_trend_engine_id",
            "requested_version": version,
            "resolved_engine_id": active_id,
            "inference_classes": {
                TREND_ENGINE_ID: "RecoveredTrendEngine (via TrendRfEngineWrapper)",
                TREND_ENGINE_V41_ID: "TrendRfV41Engine",
            },
            "execution_selection": "KernelAdapter._engine_inners() uses registry.get(resolve_active_trend_engine_id())",
            "decision_label": "strategy_selector.select_engine('TREND') returns hardcoded 'trend_rf_v40' — metadata only",
            "weights_v40": {"root": str(v40_root), "artifacts": _artifacts(v40_root)},
            "weights_v41": {"root": str(v41_root), "artifacts": _artifacts(v41_root)},
        },
        "range_routing": {
            "engine_id": RANGE_ENGINE_ID,
            "inference_class": "RangeEngineAdapter -> Phase99EngineWrapper",
            "weights": str(phase9_9_model_path(base)),
            "weights_exist": phase9_9_model_path(base).is_file(),
            "regime_gate": "select_engine('RANGE') -> phase9_9",
        },
        "registry_load": {
            "function": "EngineRegistry.build_default",
            "loads_both_trend_versions": True,
            "v41_skip_if_missing": "FileNotFoundError caught silently in build_default",
            "no_v41_to_v40_auto_fallback": True,
            "missing_v41_with_env_v41": "KernelFallbackError -> legacy PriceAction",
        },
        "overrides_found_in_code": [
            {
                "location": "tradingbot/ml/phase20a/config.py:apply_certified_env",
                "effect": "Can overwrite TREND_MODEL_VERSION and USE_ML_KERNEL",
            },
            {
                "location": "tradingbot/ml/research/phase22e|22f/config.py:configure_*_env",
                "effect": "Research runners force USE_ML_KERNEL=true and TREND_MODEL_VERSION=v41",
            },
            {
                "location": "tradingbot/config/dotenv_loader.py",
                "effect": "Will NOT override env vars already set in process",
            },
            {
                "location": "tradingbot/ml/integration/recovered_calibration.py",
                "effect": "Platt fit uses trend_rf_v40 hardcoded, not active env engine",
            },
            {
                "location": "tradingbot/ml/integration/health_gate.py:run_pre_decision_health",
                "effect": "validate_trend_checksum uses v40 paths only",
            },
        ],
        "caller_chain_live": [
            "LiveRunner.__init__ -> build_strategy_registry",
            "build_strategy_registry -> MLKernelRegistry",
            "SignalStage -> MLKernelRegistry.generate_signal",
            "KernelAdapter.produce_unified_signal",
            "resolve_active_trend_engine_id -> registry.get -> trend_inner.evaluate",
        ],
    }
