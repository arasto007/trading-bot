"""Phase 22G — production model inventory from loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_model_inventory() -> dict[str, Any]:
    from tradingbot.ml.data.paths import normalize_ml_base_dir, phase9_9_model_path
    from tradingbot.ml.integration.config import is_ml_kernel_enabled, is_ml_shadow_enabled
    from tradingbot.ml.phase15a.config import trend_rf_bundle_root
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
    from tradingbot.services.meta_labeler import MODEL_DIR, _TF_FILES

    base = normalize_ml_base_dir(None)
    active_trend = resolve_active_trend_engine_id()

    def _status(path: Path, executed: bool, loaded: bool, note: str = "") -> dict:
        return {
            "path": str(path),
            "exists": path.is_file() if path.suffix else path.is_dir(),
            "loaded_in_production_stack": loaded,
            "executed_on_signal_path": executed,
            "note": note,
        }

    meta = {tf: _status(p, executed=False, loaded=p.is_file(), note="RiskGate meta gate only") for tf, p in _TF_FILES.items()}

    items = {
        "trend_v40": _status(
            trend_rf_bundle_root(base, version="v40") / "model.pkl",
            executed=(active_trend == "trend_rf_v40"),
            loaded=True,
            note="Always registered in EngineRegistry.build_default",
        ),
        "trend_v41": _status(
            trend_rf_bundle_root(base, version="v41") / "model.pkl",
            executed=(active_trend == "trend_rf_v41"),
            loaded=(trend_rf_bundle_root(base, version="v41") / "model.pkl").is_file(),
            note="Registered only if bundle files exist; env default v41",
        ),
        "range_phase9_9": _status(
            phase9_9_model_path(base),
            executed=True,
            loaded=True,
            note="Active when regime=RANGE",
        ),
        "platt_calibration": {
            "loaded": True,
            "executed": is_ml_kernel_enabled(),
            "note": "ResearchCalibratedAdapter; fit hardcoded on trend_rf_v40 in recovered_calibration.py",
        },
        "trade_quality_engine": {
            "loaded": is_ml_kernel_enabled(),
            "executed": is_ml_kernel_enabled(),
            "note": "TradeQualityAdapter in ML stack",
        },
        "adaptive_risk_engine": {
            "loaded": is_ml_kernel_enabled(),
            "executed": is_ml_kernel_enabled(),
            "note": "MappedProductionRiskAdapter",
        },
        "meta_labeler": {
            "files": meta,
            "executed": "RiskGate.evaluate when should_gate true",
            "loaded": any(p.is_file() for p in _TF_FILES.values()),
        },
        "ml_shadow": {
            "enabled": is_ml_shadow_enabled(),
            "executed": False,
            "note": "Shadow runners under ml/integration — parallel observation, not order path",
        },
        "legacy_priceaction": {
            "loaded": True,
            "executed": "When USE_ML_KERNEL=false OR ML fallback",
            "note": "LegacyStrategyRegistry -> StrategyManager",
        },
        "paper_trading_models": {
            "loaded": False,
            "executed": False,
            "note": "tradingbot/ml/paper* — not wired to LiveRunner",
        },
        "research_engines": {
            "loaded": False,
            "executed": False,
            "note": "tradingbot/ml/research/* — phase isolated unless explicitly imported",
        },
    }

    dead = [k for k, v in items.items() if isinstance(v, dict) and not v.get("executed") and v.get("loaded") is False]
    inactive = [k for k, v in items.items() if isinstance(v, dict) and v.get("loaded") and not v.get("executed")]

    return {
        "phase": "22G",
        "active_trend_engine_id": active_trend,
        "use_ml_kernel": is_ml_kernel_enabled(),
        "models": items,
        "executed_in_live_ml_path": [k for k, v in items.items() if isinstance(v, dict) and v.get("executed") is True],
        "loaded_never_executed": inactive,
        "dead_paths": dead,
    }
