"""Phase 12.1 — strategy inventory discovery (read-only)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from tradingbot.adapters.legacy_loader import project_root
from tradingbot.config.strategies import ACTIVE_STRATEGIES
from tradingbot.ml.integration.ml_strategy import STRATEGY_NAME

# Internal SMC patterns inside priceaction (not separate registry entries)
PRICEACTION_SUB_PATTERNS = (
    "liquidity_sweep",
    "bos_ob",
    "fvg_fill",
    "order_block",
    "choch",
    "fvg",
)


def discover_strategies(*, root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    engine_strategies = _scan_engine_strategy_files(root)
    kernel_wiring = _scan_kernel_wiring(root)
    ml_strategy = _ml_strategy_info()

    registered = list(ACTIVE_STRATEGIES.keys())
    enabled = [k for k, v in ACTIVE_STRATEGIES.items() if v]
    disabled = [k for k, v in ACTIVE_STRATEGIES.items() if not v]

    production_paths = {
        "ml_shadow_paper_live": "CompositeStrategyRegistry (kernel_builder.build_kernel_shadow)",
        "legacy_live_runner": "LegacyStrategyRegistry (application.live_runner)",
        "legacy_bootstrap": "LegacyStrategyRegistry (application.bootstrap.build_kernel_live)",
    }

    return {
        "registered_in_config": registered,
        "enabled_strategies": enabled,
        "disabled_strategies": disabled,
        "engine_strategy_files": engine_strategies,
        "loaded_at_runtime": enabled,
        "ml_strategy": ml_strategy,
        "priceaction_sub_patterns": list(PRICEACTION_SUB_PATTERNS),
        "production_wiring": production_paths,
        "kernel_wiring": kernel_wiring,
        "note": (
            "Only 'priceaction' is enabled in ACTIVE_STRATEGIES. "
            "OrderBlock/CHOCH/FVG are sub-setups inside PriceActionStrategy, "
            "not independent registry strategies."
        ),
    }


def _ml_strategy_info() -> dict[str, Any]:
    return {
        "name": STRATEGY_NAME,
        "display": "Phase 9.9 ML (MLShadowStrategy)",
        "model_artifact": "data/ml/research/phase9_9_best/",
        "enabled_via_env": "ENABLE_ML_SHADOW=true",
        "registry_class": "tradingbot.ml.integration.ml_strategy.MLShadowStrategy",
    }


def _scan_engine_strategy_files(root: Path) -> list[dict[str, Any]]:
    strategies_dir = root / "engine" / "strategies"
    if not strategies_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(strategies_dir.glob("*.py")):
        if path.name.startswith("_") or path.name == "base_strategy.py":
            continue
        key = path.stem.replace("_strategy", "").replace("_", "")
        rows.append(
            {
                "file": str(path.relative_to(root)),
                "strategy_key": key,
                "enabled_in_config": ACTIVE_STRATEGIES.get(key, False),
                "class_candidates": _find_strategy_classes(path),
            }
        )
    return rows


def _find_strategy_classes(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name.endswith("Strategy")
    ]


def _scan_kernel_wiring(root: Path) -> dict[str, Any]:
    wiring: dict[str, Any] = {}
    checks = {
        "kernel_builder_shadow": root / "tradingbot" / "ml" / "integration" / "kernel_builder.py",
        "live_runner": root / "tradingbot" / "application" / "live_runner.py",
        "bootstrap_live": root / "tradingbot" / "application" / "bootstrap.py",
        "signal_stage": root / "tradingbot" / "pipeline" / "signal_stage.py",
    }
    for name, path in checks.items():
        if not path.is_file():
            wiring[name] = {"exists": False}
            continue
        text = path.read_text(encoding="utf-8")
        wiring[name] = {
            "exists": True,
            "uses_composite_registry": "CompositeStrategyRegistry" in text,
            "uses_legacy_registry": "LegacyStrategyRegistry" in text,
            "uses_ml_shadow": "MLShadowStrategy" in text or "ml_shadow" in text,
        }
    return wiring
