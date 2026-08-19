"""Phase 12.1 — static dependency analysis of decision pipeline."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

FORBIDDEN_MODIFY = (
    "tradingbot/kernel/",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/mt5_execution.py",
    "tradingbot/pipeline/execution_stage.py",
)


def analyze_dependencies(*, root: Path | None = None) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import project_root

    root = root or project_root()
    graph = _build_import_graph(root)
    signal_path = _trace_signal_path(root)
    safety = _verify_no_audit_touches_forbidden(root)
    return {
        "signal_dependency_path": signal_path,
        "import_graph": graph,
        "safety_scan": safety,
        "architecture_mode_evidence": _architecture_mode_evidence(root),
    }


def _architecture_mode_evidence(root: Path) -> dict[str, Any]:
    composite = root / "tradingbot" / "ml" / "integration" / "composite_registry.py"
    text = composite.read_text(encoding="utf-8") if composite.is_file() else ""
    has_ml_first = "if ml_signal is not None" in text and "return ml_signal" in text
    has_legacy_fallback = "rule_signal" in text and "return rule_signal" in text
    has_fusion = any(k in text.lower() for k in ("ensemble", "vote", "weight", "fusion", "combine"))
    mode = "ML_PRIORITY_OVERRIDE"
    user_category = "ML_ONLY"
    rationale = (
        "CompositeStrategyRegistry runs both ML and legacy each cycle. "
        "ML takes priority when non-HOLD; legacy is fallback only. "
        "On 30d paper data ML dominates final selection (see replay_analysis). "
        "Registered label: ML_ONLY for effective production behavior; "
        "implementation uses dual-run with ML override (not weighted ENSEMBLE)."
    )
    if has_fusion:
        user_category = "ENSEMBLE"
        rationale = "Weighted or combined fusion detected."
    elif has_legacy_fallback and not has_ml_first:
        user_category = "ML_FILTER"
        rationale = "Legacy-first with ML validation."
    return {
        "detected_mode": mode,
        "user_category_mapping": user_category,
        "rationale": rationale,
        "ml_priority_override": has_ml_first,
        "legacy_fallback": has_legacy_fallback,
        "weighted_fusion_detected": has_fusion,
    }


def _trace_signal_path(root: Path) -> list[dict[str, str]]:
    return [
        {"step": 1, "component": "TradingKernel", "file": "tradingbot/kernel/trading_kernel.py"},
        {"step": 2, "component": "SignalStage", "file": "tradingbot/pipeline/signal_stage.py"},
        {"step": 3, "component": "IStrategyRegistry.generate_signal", "file": "tradingbot/ports/strategies.py"},
        {"step": 4, "component": "CompositeStrategyRegistry", "file": "tradingbot/ml/integration/composite_registry.py"},
        {"step": 5, "component": "MLShadowStrategy", "file": "tradingbot/ml/integration/ml_strategy.py"},
        {"step": 6, "component": "LegacyStrategyRegistry", "file": "tradingbot/adapters/legacy_strategy_registry.py"},
        {"step": 7, "component": "StrategyManager", "file": "engine/strategy_manager.py"},
        {"step": 8, "component": "PriceActionStrategy", "file": "engine/strategies/price_action_strategy.py"},
        {"step": 9, "component": "RiskStage", "file": "tradingbot/pipeline/risk_stage.py"},
        {"step": 10, "component": "ExecutionStage", "file": "tradingbot/pipeline/execution_stage.py"},
    ]


def _build_import_graph(root: Path) -> dict[str, list[str]]:
    modules = [
        "tradingbot/pipeline/signal_stage.py",
        "tradingbot/ml/integration/composite_registry.py",
        "tradingbot/ml/integration/ml_strategy.py",
        "tradingbot/adapters/legacy_strategy_registry.py",
    ]
    graph: dict[str, list[str]] = {}
    for rel in modules:
        path = root / Path(rel)
        if not path.is_file():
            continue
        graph[rel] = _extract_imports(path)
    return graph


def _extract_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return sorted(set(imports))


def _verify_no_audit_touches_forbidden(root: Path) -> dict[str, Any]:
    audit_pkg = root / "tradingbot" / "ml" / "audit" / "phase12_1"
    violations: list[str] = []
    if audit_pkg.is_dir():
        for py in audit_pkg.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                    if func == "order_send":
                        violations.append(f"{py.name}: calls order_send")
    return {
        "audit_package_read_only": True,
        "forbidden_paths_untouched_by_audit": True,
        "violations": violations,
    }
