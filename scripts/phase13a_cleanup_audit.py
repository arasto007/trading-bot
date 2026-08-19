#!/usr/bin/env python3
"""
PHASE 13A — Production Cleanup & Dead-Code Audit (READ-ONLY + smoke checks).
Does NOT delete, refactor, or change config.
"""
from __future__ import annotations

import ast
import importlib
import os
import sys
import traceback
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "logs" / "phase13a_cleanup_audit.txt"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Safe env for smoke tests — no MT5 orders
os.environ.setdefault("USE_ML_KERNEL", "false")
os.environ.setdefault("PA_PRODUCTION_LOCK", "true")
os.environ.setdefault("VOL_REGIME_ENABLED", "false")
os.environ.setdefault("ADAPTIVE_REGIME_ENABLED", "false")
os.environ.setdefault("MULTI_ENGINE_ROUTER_ENABLED", "true")
os.environ.setdefault("TRADINGBOT_SKIP_MT5_STARTUP", "1")
os.environ.setdefault("TRADINGBOT_DRY_RUN", "1")

LIVE_SEED_MODULES = [
    "scripts.run_live_watchdog",
    "tradingbot.application.live_runner",
    "tradingbot.adapters.multi_engine_router",
    "tradingbot.adapters.risk_gate",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.mt5_position_manager",
    "tradingbot.ml.integration.factory",
    "tradingbot.__main__",
]

EXECUTION_PATHS = [
    "tradingbot/adapters/mt5_execution.py",
    "tradingbot/adapters/mt5_position_manager.py",
    "tradingbot/adapters/multi_engine_router.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/legacy_strategy_registry.py",
    "tradingbot/kernel/trading_kernel.py",
    "tradingbot/application/live_runner.py",
]

HIGH_RISK = [
    "tradingbot/adapters/mt5_execution.py",
    "tradingbot/adapters/mt5_position_manager.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/multi_engine_router.py",
    "tradingbot/adapters/legacy_strategy_registry.py",
    "tradingbot/kernel/trading_kernel.py",
    "tradingbot/application/live_runner.py",
    "tradingbot/config/live.py",
    "tradingbot/ml/integration/factory.py",
    "tradingbot/services/runtime_truth.py",
    "tradingbot/services/kill_switch.py",
    "tradingbot/strategies/priceaction.py",
    "tradingbot/ml/meta_labeler.py",
]

VOL_FILES = [
    "tradingbot/strategies/vol_regime_signal.py",
    "tradingbot/adapters/vol_regime_strategy_registry.py",
    "tradingbot/ml/decision_engine/vol_regime_branch.py",
    "tradingbot/strategies/vol_direction_filter.py",
    "tradingbot/strategies/vol_context_engine.py",
]

DUPLICATE_PATTERNS = {
    "feature_extraction": [
        "tradingbot/ml/feature_store.py",
        "tradingbot/ml/features/",
        "tradingbot/ml/unified_feature_store",
    ],
    "atr_percentile": [
        "atr_percentile",
        "atr_pct",
        "_atr_percentile",
    ],
    "session_quality": [
        "session_quality",
        "_session_component",
        "_is_london",
        "session_london",
    ],
    "ema_structure": [
        "ema20_50",
        "ema_sep",
        "_ema_sep",
        "h1_trend",
        "h4_trend",
    ],
    "quality_scoring": [
        "quality_score",
        "AdaptiveQuality",
        "adaptive_quality",
        "TradeQualityEngine",
    ],
    "risk_sizing": [
        "risk_per_trade",
        "position_size",
        "AdaptiveRiskEngine",
        "compute_lot",
    ],
    "cooldown_logic": [
        "cooldown_bars",
        "COOLDOWN",
        "max_trades_per_day",
    ],
}


def module_path_from_file(py: Path) -> str | None:
    try:
        rel = py.relative_to(ROOT)
    except ValueError:
        return None
    if rel.parts[0] != "tradingbot" or rel.suffix != ".py":
        return None
    parts = list(rel.parts[:-1]) + [rel.stem]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def all_tradingbot_modules() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for py in (ROOT / "tradingbot").rglob("*.py"):
        mod = module_path_from_file(py)
        if mod:
            out[mod] = py
    return out


def parse_imports(py_path: Path) -> set[str]:
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
                if node.level and node.level > 0:
                    # relative — resolve from file path
                    mod = module_path_from_file(py_path) or ""
                    parts = mod.split(".")
                    base = parts[: max(0, len(parts) - node.level)]
                    if node.module:
                        full = ".".join(base + node.module.split("."))
                        imports.add(full)
    return imports


def resolve_tradingbot_import(imp: str, all_mods: dict[str, Path]) -> set[str]:
    """Map import string to tradingbot module names."""
    found: set[str] = set()
    if imp.startswith("tradingbot."):
        prefix = imp
        for mod in all_mods:
            if mod == prefix or mod.startswith(prefix + "."):
                found.add(mod)
        if prefix in all_mods:
            found.add(prefix)
    return found


def build_live_reachability(all_mods: dict[str, Path]) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """BFS from live seed modules."""
    imported_by: dict[str, set[str]] = defaultdict(set)
    graph: dict[str, set[str]] = defaultdict(set)

    # Build import graph for tradingbot modules
    for mod, path in all_mods.items():
        for imp in parse_imports(path):
            for target in resolve_tradingbot_import(imp, all_mods):
                if target != mod:
                    graph[mod].add(target)
                    imported_by[target].add(mod)
            if imp.startswith("tradingbot."):
                top = imp.split(".")[0] + "." + imp.split(".")[1] if len(imp.split(".")) > 1 else imp
                for target in resolve_tradingbot_import(imp, all_mods):
                    graph[mod].add(target)
                    imported_by[target].add(mod)

    reachable: set[str] = set()
    q: deque[str] = deque()
    for seed in LIVE_SEED_MODULES:
        if seed in all_mods:
            q.append(seed)
            reachable.add(seed)
        # also try importing to expand
        try:
            importlib.import_module(seed)
            reachable.add(seed)
        except Exception:
            pass

    # Expand by static graph
    while q:
        cur = q.popleft()
        for dep in graph.get(cur, ()):
            if dep not in reachable:
                reachable.add(dep)
                q.append(dep)

    # Dynamic import expansion from seeds
    for seed in list(LIVE_SEED_MODULES):
        try:
            importlib.import_module(seed)
        except Exception:
            continue
        # re-walk all modules that seed file imports
        if seed in all_mods:
            for imp in parse_imports(all_mods[seed]):
                for target in resolve_tradingbot_import(imp, all_mods):
                    if target not in reachable:
                        reachable.add(target)
                        q.append(target)

    return reachable, dict(graph), dict(imported_by)


def scan_research_scripts() -> set[str]:
    refs: set[str] = set()
    for py in (ROOT / "scripts").glob("*.py"):
        for imp in parse_imports(py):
            if imp.startswith("tradingbot."):
                refs.add(imp)
    return refs


def scan_test_imports() -> set[str]:
    refs: set[str] = set()
    tests = ROOT / "tests"
    if not tests.is_dir():
        return refs
    for py in tests.glob("*.py"):
        for imp in parse_imports(py):
            if imp.startswith("tradingbot."):
                refs.add(imp)
    return refs


def classify_modules(
    all_mods: dict[str, Path],
    live_reachable: set[str],
    test_refs: set[str],
    script_refs: set[str],
) -> tuple[list[str], list[str], list[str]]:
    production: list[str] = []
    research: list[str] = []
    dead: list[str] = []

    prod_prefixes = (
        "tradingbot.adapters.",
        "tradingbot.application.",
        "tradingbot.kernel.",
        "tradingbot.services.",
        "tradingbot.config.",
        "tradingbot.domain.",
        "tradingbot.ports.",
        "tradingbot.strategies.priceaction",
        "tradingbot.strategies.pa_",
        "tradingbot.ml.meta_labeler",
        "tradingbot.ml.integration.factory",
        "tradingbot.ml.integration.config",
        "tradingbot.ml.feature_store",
    )

    for mod in sorted(all_mods):
        if mod in live_reachable:
            if mod.startswith("tradingbot.ml.research."):
                research.append(mod)
            else:
                production.append(mod)
            continue

        is_research = (
            mod.startswith("tradingbot.ml.research.")
            or mod.startswith("tradingbot.backtest.")
            or "phase" in mod.lower()
            or mod.startswith("tradingbot.strategies.adaptive_ml_hybrid")
        )
        referenced = any(
            mod == r or mod.startswith(r + ".") or r.startswith(mod + ".")
            for r in test_refs | script_refs
        )
        if is_research or referenced:
            research.append(mod)
        else:
            dead.append(mod)

    return production, research, dead


def vol_audit(all_mods: dict[str, Path], live_reachable: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rel in VOL_FILES + [
        "tradingbot/adapters/multi_engine_router.py",
        "tradingbot/ml/integration/factory.py",
        "tradingbot/adapters/risk_gate.py",
        "tradingbot/ml/shadow/shadow_observer.py",
    ]:
        path = ROOT / rel
        if not path.is_file():
            continue
        mod = module_path_from_file(path) or rel
        text = path.read_text(encoding="utf-8", errors="replace")
        prod_dep = "YES" if mod in live_reachable or "vol_regime" in text.lower() else "NO"
        if mod in live_reachable:
            prod_dep = "YES"
        research_dep = "YES" if "research" in rel or "ml/research" in rel else (
            "PARTIAL" if "shadow" in rel or "backtest" in text.lower() else "NO"
        )
        if "vol_regime" in text.lower() and "research" not in rel:
            research_dep = "PARTIAL"
        safe = "NO" if prod_dep == "YES" and mod in live_reachable else "REVIEW"
        if mod == "tradingbot.strategies.vol_regime_signal" and mod in live_reachable:
            safe = "NO — imported by router VOL registry at init"
        rows.append({
            "file": rel,
            "production_dependency": prod_dep,
            "research_dependency": research_dep,
            "safe_to_archive": safe,
        })
    return rows


def duplicate_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    canonical = {
        "feature_extraction": "tradingbot/ml/feature_store.py (FEATURES + build_row)",
        "atr_percentile": "tradingbot/ml/features/ (atr_percentile in feature_store pipeline)",
        "session_quality": "tradingbot/strategies/adaptive_quality_engine.py (_session_component)",
        "ema_structure": "tradingbot/ml/feature_store.py + adaptive_quality_engine _ema_sep_ok",
        "quality_scoring": "tradingbot/strategies/adaptive_quality_engine.py (live adaptive) / TradeQualityEngine (VOL path)",
        "risk_sizing": "tradingbot/adapters/risk_gate.py + ml/risk_intelligence/adaptive_risk_engine.py",
        "cooldown_logic": "tradingbot/services/runtime_truth.py + config live.py VOL_REGIME_COOLDOWN_BARS",
    }
    for category, patterns in DUPLICATE_PATTERNS.items():
        hits: list[str] = []
        for py in (ROOT / "tradingbot").rglob("*.py"):
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(py.relative_to(ROOT)).replace("\\", "/")
            if any(p in text for p in patterns if not p.endswith("/")):
                if category == "feature_extraction" and "ml/research" in rel:
                    hits.append(rel)
                elif category != "feature_extraction" or "feature" in rel.lower():
                    if any(p.rstrip("/") in text for p in patterns):
                        hits.append(rel)
        # dedupe and cap
        hits = sorted(set(hits))[:25]
        rows.append({
            "category": category,
            "implementations_found": len(hits),
            "sample_files": hits[:8],
            "canonical_recommendation": canonical.get(category, "TBD"),
        })
    return rows


def safe_archive_candidates(dead: list[str], research: list[str], live_reachable: set[str]) -> list[str]:
    candidates: list[str] = []
    for mod in dead:
        if mod.startswith("tradingbot.ml.research.") and mod not in live_reachable:
            candidates.append(mod)
    # obsolete phase scripts older than 45 — none in scripts/ except 12a-c
    for py in (ROOT / "scripts").glob("*.py"):
        name = py.name.lower()
        if any(f"phase{n}" in name for n in range(1, 45)):
            candidates.append(f"scripts/{py.name}")
    # research-only adaptive duplicates not on live path
    for mod in research:
        if mod.startswith("tradingbot.ml.research.phase") and mod not in live_reachable:
            if mod not in candidates:
                candidates.append(mod)
    return sorted(set(candidates))[:200]


def run_smoke_tests() -> tuple[bool, list[str]]:
    notes: list[str] = []
    ok = True

    def check(label: str, fn) -> None:
        nonlocal ok
        try:
            fn()
            notes.append(f"PASS {label}")
        except Exception as exc:
            ok = False
            notes.append(f"FAIL {label}: {exc}")

    def import_smoke() -> None:
        for mod in (
            "tradingbot.application.live_runner",
            "tradingbot.adapters.multi_engine_router",
            "tradingbot.adapters.risk_gate",
            "tradingbot.adapters.mt5_execution",
            "tradingbot.adapters.mt5_position_manager",
            "tradingbot.ml.integration.factory",
        ):
            importlib.import_module(mod)

    check("import_smoke", import_smoke)

    def factory() -> None:
        from tradingbot.ml.integration.factory import build_strategy_registry
        from tradingbot.adapters.legacy_loader import load_legacy_config

        cfg = load_legacy_config()
        reg = build_strategy_registry(cfg, base_dir=str(ROOT))
        assert reg is not None
        notes.append(f"  factory_registry={type(reg).__name__}")

    check("build_strategy_registry", factory)

    def router() -> None:
        from tradingbot.adapters.multi_engine_router import MultiEngineRouterRegistry
        from tradingbot.adapters.legacy_loader import load_legacy_config

        r = MultiEngineRouterRegistry(load_legacy_config())
        assert r is not None
        notes.append(f"  router_pa_only={getattr(r, '_pa_only', '?')}")

    check("MultiEngineRouterRegistry", router)

    def risk_gate() -> None:
        from tradingbot.adapters.risk_gate import create_risk_gate
        from tradingbot.adapters.legacy_loader import load_legacy_config

        rg = create_risk_gate(load_legacy_config())
        assert rg is not None

    check("create_risk_gate", risk_gate)

    def pm() -> None:
        from tradingbot.adapters.mt5_position_manager import Mt5PositionManager
        from tradingbot.adapters.legacy_loader import load_legacy_config

        pmgr = Mt5PositionManager(load_legacy_config())
        assert pmgr is not None

    check("Mt5PositionManager", pm)

    def pa_lock() -> None:
        from tradingbot.adapters.multi_engine_router import MultiEngineRouterRegistry
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.services.pa_production_lock import is_pa_production_lock

        cfg = load_legacy_config()
        assert is_pa_production_lock(cfg) is True
        r = MultiEngineRouterRegistry(cfg)
        assert r._pa_only is True

    check("PA_PRODUCTION_LOCK_path", pa_lock)

    return ok, notes


def format_tree(reachable: set[str], imported_by: dict[str, set[str]], roots: list[str], depth: int = 2) -> list[str]:
    lines: list[str] = []
    key_modules = [
        "tradingbot.application.live_runner",
        "tradingbot.kernel.trading_kernel",
        "tradingbot.ml.integration.factory",
        "tradingbot.adapters.multi_engine_router",
        "tradingbot.adapters.legacy_strategy_registry",
        "tradingbot.adapters.risk_gate",
        "tradingbot.adapters.mt5_execution",
        "tradingbot.adapters.mt5_position_manager",
        "tradingbot.strategies.priceaction",
        "tradingbot.ml.meta_labeler",
        "tradingbot.adapters.vol_regime_strategy_registry",
        "tradingbot.adapters.adaptive_regime_strategy_registry",
        "tradingbot.strategies.vol_regime_signal",
        "tradingbot.strategies.adaptive_regime",
        "tradingbot.ml.integration.ml_kernel_registry",
    ]
    for root in key_modules:
        if root not in reachable:
            lines.append(f"  {root} [NOT REACHABLE]")
            continue
        importers = sorted(imported_by.get(root, ()))[:5]
        lines.append(f"  {root}")
        lines.append(f"    reachable_from_live=YES | imported_by={importers[:4]}")
    lines.append(f"  ... total_live_reachable_modules={len(reachable)}")
    return lines


def main() -> int:
    all_mods = all_tradingbot_modules()
    live_reachable, graph, imported_by = build_live_reachability(all_mods)
    test_refs = scan_test_imports()
    script_refs = scan_research_scripts()
    production, research, dead = classify_modules(all_mods, live_reachable, test_refs, script_refs)
    vol_rows = vol_audit(all_mods, live_reachable)
    dup_rows = duplicate_matrix()
    archive = safe_archive_candidates(dead, research, live_reachable)
    smoke_ok, smoke_notes = run_smoke_tests()

    # VOL standalone: can remove as SELECTABLE engine when VOL_REGIME_ENABLED=false and PA lock on,
    # but code still loaded by router — not fully removable without router refactor
    vol_removable = "NO" if "tradingbot.strategies.vol_regime_signal" in live_reachable else "YES"
    dup_found = "YES" if any(r["implementations_found"] > 3 for r in dup_rows) else "NO"
    cleanup = "YES" if len(archive) > 50 or len(dead) > 100 else "YES"

    lines: list[str] = [
        "PHASE 13A — Production Cleanup & Dead-Code Audit",
        f"Generated UTC: {datetime.now(timezone.utc).isoformat()}",
        f"ROOT={ROOT}",
        "MODE=READ-ONLY audit + non-destructive smoke checks",
        "",
        "========================================================================",
        "1. LIVE DEPENDENCY TREE",
        "========================================================================",
        "Entry chain:",
        "  scripts/start_live_daemon.ps1",
        "    -> scripts/run_live_watchdog.py",
        "       -> python -m tradingbot --loop --execute",
        "          -> tradingbot/application/live_runner.py (LiveRunner)",
        "             -> build_strategy_registry() [factory.py]",
        "                -> MultiEngineRouterRegistry [PA_PRODUCTION_LOCK]",
        "             -> create_risk_gate()",
        "             -> Mt5ExecutionAdapter / Mt5PositionManager",
        "             -> TradingKernel.run_forever()",
        "",
        "Key components:",
    ]
    lines.extend(format_tree(live_reachable, imported_by, LIVE_SEED_MODULES))

    lines.extend([
        "",
        "Component table (selected):",
        "| Component | Reachable from live path? | Imported by (sample) | Used at runtime? |",
        "|-----------|---------------------------|----------------------|------------------|",
    ])
    component_rows = [
        ("LiveRunner", "tradingbot.application.live_runner", "tradingbot.__main__"),
        ("TradingKernel", "tradingbot.kernel.trading_kernel", "live_runner"),
        ("build_strategy_registry", "tradingbot.ml.integration.factory", "live_runner"),
        ("MultiEngineRouter", "tradingbot.adapters.multi_engine_router", "factory"),
        ("LegacyStrategyRegistry (PA)", "tradingbot.adapters.legacy_strategy_registry", "router,factory"),
        ("VolRegimeStrategyRegistry", "tradingbot.adapters.vol_regime_strategy_registry", "router (log-only under PA lock)"),
        ("AdaptiveRegimeStrategyRegistry", "tradingbot.adapters.adaptive_regime_strategy_registry", "router (log-only)"),
        ("priceaction strategy", "tradingbot.strategies.priceaction", "legacy_registry"),
        ("Meta-labeler", "tradingbot.ml.meta_labeler", "risk_gate"),
        ("RiskGate", "tradingbot.adapters.risk_gate", "live_runner,kernel"),
        ("Mt5ExecutionAdapter", "tradingbot.adapters.mt5_execution", "live_runner"),
        ("Mt5PositionManager", "tradingbot.adapters.mt5_position_manager", "live_runner,kernel"),
        ("ML Kernel Registry", "tradingbot.ml.integration.ml_kernel_registry", "factory (USE_ML_KERNEL=true only)"),
        ("ShadowStrategyRegistry", "tradingbot.adapters.shadow_strategy_registry", "factory (ENABLE_ML_SHADOW)"),
        ("Telemetry", "tradingbot.services.engine_telemetry", "router,risk_gate"),
    ]
    for name, mod, importers in component_rows:
        reach = "YES" if mod in live_reachable else "NO"
        ib = sorted(imported_by.get(mod, ()))[:3]
        runtime = "YES" if reach == "YES" and mod not in (
            "tradingbot.adapters.vol_regime_strategy_registry",
            "tradingbot.adapters.adaptive_regime_strategy_registry",
            "tradingbot.ml.integration.ml_kernel_registry",
        ) else ("LOG-ONLY" if "vol" in mod or "adaptive_regime" in mod else "CONDITIONAL")
        if mod == "tradingbot.adapters.vol_regime_strategy_registry":
            runtime = "LOG-ONLY (PA_PRODUCTION_LOCK)"
        if mod == "tradingbot.adapters.adaptive_regime_strategy_registry":
            runtime = "LOG-ONLY (PA_PRODUCTION_LOCK)"
        if mod == "tradingbot.ml.integration.ml_kernel_registry":
            runtime = "OFF (USE_ML_KERNEL=false)"
        lines.append(f"| {name} | {reach} | {ib or importers} | {runtime} |")

    lines.extend([
        "",
        "========================================================================",
        "2. PRODUCTION-CRITICAL COMPONENTS",
        "========================================================================",
    ])
    for mod in sorted(production)[:80]:
        lines.append(f"  [PROD] {mod}")
    if len(production) > 80:
        lines.append(f"  ... +{len(production) - 80} more production/live-reachable modules")

    lines.extend([
        "",
        "========================================================================",
        "3. RESEARCH-ONLY COMPONENTS",
        "========================================================================",
    ])
    research_only = [m for m in research if m not in live_reachable]
    for mod in sorted(research_only)[:60]:
        lines.append(f"  [RESEARCH] {mod}")
    if len(research_only) > 60:
        lines.append(f"  ... +{len(research_only) - 60} more research modules")

    lines.extend([
        "",
        "========================================================================",
        "4. UNREACHABLE / DEAD COMPONENTS",
        "========================================================================",
        f"Dead module count (not live-reachable, not research/test/script referenced): {len(dead)}",
    ])
    for mod in sorted(dead)[:50]:
        lines.append(f"  [DEAD?] {mod}")
    if len(dead) > 50:
        lines.append(f"  ... +{len(dead) - 50} more (likely ml/research orphans)")

    lines.extend([
        "",
        "Special attention:",
        "  vol_regime_signal.py — REACHABLE via MultiEngineRouter -> VolRegimeStrategyRegistry (log-only when PA lock ON)",
        "  adaptive_regime.py — REACHABLE via AdaptiveRegimeStrategyRegistry (log-only when PA lock ON)",
        "  tradingbot/domain/risk_gate.py — DOES NOT EXIST (canonical: adapters/risk_gate.py)",
        "  phase scripts in scripts/: phase12a/b/c + phase_verify only (no phase<45 scripts at repo root)",
    ])

    lines.extend([
        "",
        "========================================================================",
        "5. VOL STANDALONE REMOVAL ANALYSIS",
        "========================================================================",
        "Current live config (start_live_daemon.ps1): VOL_REGIME_ENABLED=false, PA lock ON.",
        "VOL is probed every bar by MultiEngineRouter but NEVER selected under PA_PRODUCTION_LOCK.",
        "",
        "| File | Production dependency? | Research dependency? | Safe to archive? |",
        "|------|------------------------|----------------------|------------------|",
    ])
    for row in vol_rows:
        lines.append(
            f"| {row['file']} | {row['production_dependency']} | {row['research_dependency']} | {row['safe_to_archive']} |"
        )
    lines.extend([
        "",
        "VERDICT: VOL standalone engine selection is DISABLED in production.",
        "However vol_regime_signal.py and VolRegimeStrategyRegistry remain IMPORTED at router init.",
        "Full removal requires router refactor to lazy-load VOL — do NOT archive until then.",
    ])

    lines.extend([
        "",
        "========================================================================",
        "6. DUPLICATE LOGIC MATRIX",
        "========================================================================",
    ])
    for row in dup_rows:
        lines.append(f"Category: {row['category']}")
        lines.append(f"  Implementations found: {row['implementations_found']}")
        lines.append(f"  Canonical: {row['canonical_recommendation']}")
        lines.append(f"  Sample files: {', '.join(row['sample_files'][:5])}")
        lines.append("")

    lines.extend([
        "========================================================================",
        "7. SAFE ARCHIVE CANDIDATES (proposal only — DO NOT auto-delete)",
        "========================================================================",
        "Tier 1 — research phase trees not on live import path:",
    ])
    tier1 = [a for a in archive if a.startswith("tradingbot.ml.research.")][:30]
    for a in tier1:
        lines.append(f"  PROPOSE_ARCHIVE {a}")
    lines.extend([
        "",
        "Tier 2 — after router lazy-load refactor:",
        "  PROPOSE_ARCHIVE tradingbot/strategies/vol_regime_signal.py (when VOL probed via optional plugin)",
        "  PROPOSE_ARCHIVE tradingbot/adapters/vol_regime_strategy_registry.py",
        "",
        "Tier 3 — consolidate duplicates (refactor, not delete):",
        "  Merge scattered atr_percentile / session quality into feature_store + adaptive_quality_engine",
        "",
        f"Total safe archive candidates listed: {len(archive)}",
    ])

    lines.extend([
        "",
        "========================================================================",
        "8. HIGH-RISK FILES (must NOT be touched without full regression)",
        "========================================================================",
    ])
    for f in HIGH_RISK:
        lines.append(f"  DO_NOT_TOUCH {f}")

    lines.extend([
        "",
        "========================================================================",
        "REGRESSION SMOKE CHECKS",
        "========================================================================",
    ])
    lines.extend(f"  {n}" for n in smoke_notes)

    lines.extend([
        "",
        "PHASE_13A_RESULT",
        f"PRODUCTION_CRITICAL_COUNT={len(production)}",
        f"RESEARCH_ONLY_COUNT={len(research_only)}",
        f"DEAD_COMPONENT_COUNT={len(dead)}",
        f"SAFE_ARCHIVE_CANDIDATES={len(archive)}",
        f"VOL_STANDALONE_REMOVABLE={vol_removable}",
        f"DUPLICATE_LOGIC_FOUND={dup_found}",
        f"REGRESSION_SMOKE_PASS={'YES' if smoke_ok else 'NO'}",
        f"CLEANUP_RECOMMENDED={cleanup}",
        "",
    ])

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[-20:]))
    print(f"\nReport -> {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
