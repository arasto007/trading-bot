"""Inspect the repository and write machine-readable audit JSON. No MT5. No .env secrets."""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SKIP_DIR = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".mypy_cache",
    ".cursor",
}


def _walk_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR for part in p.parts):
            continue
        out.append(p)
    return out


def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def _classify_path(rel: str) -> str:
    low = rel.lower()
    if low.startswith("tests/"):
        return "TEST"
    if "/research/" in low or low.startswith("tradingbot/research/") or low.startswith("scripts/phase") or low.startswith("scripts/run_phase"):
        return "RESEARCH"
    if low.startswith("docs") or low.startswith("memory/"):
        return "DOCS"
    if low.startswith("data/ml/reports/") or low.endswith(".json") and "reports" in low:
        return "ARTIFACT"
    if low.startswith("tradingbot/") or low.startswith("engine/") or low.startswith("scripts/start"):
        return "PRODUCTION_CANDIDATE"
    return "OTHER"


def _top_level_public(path: Path) -> dict[str, list[str]]:
    classes: list[str] = []
    functions: list[str] = []
    constants: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (OSError, SyntaxError):
        return {"classes": [], "functions": [], "constants": []}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            classes.append(node.name)
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            functions.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("_"):
                    constants.append(t.id)
    return {"classes": classes, "functions": functions, "constants": constants}


def _has_main_guard(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return '__name__ == "__main__"' in text or "__name__ == '__main__'" in text


def _import_edges(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
    return sorted(set(out))


def _count_todo(py_files: list[Path]) -> dict[str, int]:
    keys = ("TODO", "FIXME", "XXX", "HACK")
    counts = Counter()
    for p in py_files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k in keys:
            counts[k] += text.count(k)
    return dict(counts)


def _entry_points() -> list[dict[str, Any]]:
    return [
        {
            "id": "default_live_daemon",
            "class": "A",
            "chain": [
                "start/START_BOT.bat",
                "scripts/start_bot.py",
                "scripts/start_live_daemon.ps1",
                "scripts/run_live_watchdog.py --execute",
                "python -m tradingbot --loop --execute",
                "tradingbot/__main__.py::main",
                "tradingbot/application/live_runner.py::run_live_loop",
                "tradingbot/application/bootstrap.py::build_kernel_live",
                "tradingbot/kernel/trading_kernel.py::TradingKernel.run_forever",
            ],
        },
        {
            "id": "cli_live_cycle",
            "class": "A",
            "chain": ["python -m tradingbot --live", "bootstrap.run_live_cycle"],
        },
        {
            "id": "cli_backtest",
            "class": "B",
            "chain": ["python -m tradingbot --backtest", "tradingbot/backtest/engine.py::BacktestEngine"],
        },
        {
            "id": "cli_paper",
            "class": "B",
            "chain": ["python -m tradingbot --paper"],
        },
        {
            "id": "cli_strategies_stub",
            "class": "F",
            "chain": ["python -m tradingbot --strategies", "bootstrap.run_strategies_cycle"],
        },
        {
            "id": "healthcheck",
            "class": "F",
            "chain": ["python -m tradingbot --healthcheck", "live_loop_health"],
        },
        {
            "id": "ml_research",
            "class": "D",
            "chain": ["scripts/run_phase*.py", "tradingbot/ml/research/*"],
        },
        {
            "id": "isolated_v41",
            "class": "E",
            "chain": ["tradingbot/ml/research/v41_isolated/run.py"],
        },
        {
            "id": "isolated_pa_audit",
            "class": "E",
            "chain": ["tradingbot/ml/research/pa_live_audit/run.py"],
        },
        {
            "id": "pytest",
            "class": "F",
            "chain": ["tests/"],
        },
    ]


def _live_call_chain() -> list[dict[str, str]]:
    return [
        {"file": "scripts/start_bot.py", "symbol": "main/subprocess → start_live_daemon.ps1"},
        {"file": "scripts/start_live_daemon.ps1", "symbol": "sets USE_ML_KERNEL=false if unset"},
        {"file": "scripts/run_live_watchdog.py", "symbol": "_bot_cmd → python -m tradingbot --loop --execute"},
        {"file": "tradingbot/__main__.py", "symbol": "main → run_live_loop"},
        {"file": "tradingbot/application/live_runner.py", "symbol": "run_live_loop / LiveRunner"},
        {"file": "tradingbot/application/bootstrap.py", "symbol": "build_kernel_live"},
        {"file": "tradingbot/ml/integration/factory.py", "symbol": "build_strategy_registry"},
        {"file": "tradingbot/adapters/multi_engine_router.py", "symbol": "MultiEngineRouterRegistry.generate_signal"},
        {"file": "tradingbot/adapters/legacy_strategy_registry.py", "symbol": "LegacyStrategyRegistry.generate_signal"},
        {"file": "engine/strategy_manager.py", "symbol": "StrategyManager.generate_combined_signals"},
        {"file": "engine/strategies/price_action_strategy.py", "symbol": "PriceActionStrategy.generate_signals"},
        {"file": "tradingbot/domain/gold_strategies/router.py", "symbol": "evaluate_gold_setup"},
        {"file": "tradingbot/domain/gold_strategies/m5_london_sweep.py", "symbol": "evaluate_m5_london_sweep"},
        {"file": "tradingbot/domain/pa_hardening.py", "symbol": "apply_setup_hardening"},
        {"file": "tradingbot/domain/signal_helpers.py", "symbol": "build_trading_signal"},
        {"file": "tradingbot/pipeline/signal_stage.py", "symbol": "SignalStage.run + exclude_forming_bar"},
        {"file": "tradingbot/pipeline/risk_stage.py", "symbol": "RiskStage → RiskGate.evaluate"},
        {"file": "tradingbot/adapters/risk_gate.py", "symbol": "RiskGate.evaluate"},
        {"file": "tradingbot/pipeline/execution_stage.py", "symbol": "ExecutionStage"},
        {"file": "tradingbot/adapters/mt5_execution.py", "symbol": "Mt5ExecutionAdapter"},
    ]


def _bundle_meta(version: str) -> dict[str, Any]:
    from tradingbot.ml.phase15a.config import trend_rf_bundle_root

    root = trend_rf_bundle_root(version=version)
    out: dict[str, Any] = {"path": str(root), "present": root.is_dir()}
    chk = root / "checksum.json"
    if chk.is_file():
        out["checksum"] = json.loads(chk.read_text(encoding="utf-8"))
    meta = root / "metadata.json"
    if meta.is_file():
        out["metadata"] = json.loads(meta.read_text(encoding="utf-8"))
    return out


def run_full_repo_audit(*, write_reports: bool = True) -> dict[str, Any]:
    from tradingbot.config.live import LIVE_TRADING_CONFIG, PRIMARY_SYMBOL
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.config.strategies import ACTIVE_STRATEGIES
    from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID
    from tradingbot.ml.integration.config import is_ml_kernel_enabled
    from tradingbot.ml.integration.kernel_adapter import PIPELINE_TIMEOUT_MS
    from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    files = _walk_files()
    by_ext = Counter(p.suffix.lower() or "<none>" for p in files)
    py = [p for p in files if p.suffix == ".py"]
    classified = Counter(_classify_path(_rel(p)) for p in py)
    packages = sorted(
        {
            _rel(p.parent)
            for p in files
            if p.name == "__init__.py" and "tradingbot" in p.parts
        }
    )
    tests = [_rel(p) for p in files if p.suffix == ".py" and "tests" in p.parts and p.name.startswith("test_")]
    docs = [_rel(p) for p in files if p.suffix.lower() in {".md", ".rst"}]
    scripts = sorted(_rel(p) for p in files if p.parts[0] == "scripts" and p.suffix.lower() in {".py", ".ps1", ".bat"})
    config_files = sorted(
        _rel(p)
        for p in files
        if p.suffix.lower() in {".py", ".json", ".yml", ".yaml", ".toml", ".ini", ".env"}
        and (
            "config" in p.parts
            or p.name in {"pytest.ini", ".env.example"}
            or p.name.endswith(".env.example")
        )
    )
    file_records = [
        {
            "path": _rel(p),
            "ext": p.suffix.lower() or "<none>",
            "class": _classify_path(_rel(p)),
            "has_main": _has_main_guard(p) if p.suffix == ".py" else False,
        }
        for p in files
    ]
    key_modules = [
        "tradingbot/__main__.py",
        "tradingbot/application/bootstrap.py",
        "tradingbot/application/live_runner.py",
        "tradingbot/kernel/trading_kernel.py",
        "tradingbot/ml/integration/factory.py",
        "tradingbot/adapters/multi_engine_router.py",
        "tradingbot/adapters/legacy_strategy_registry.py",
        "tradingbot/adapters/risk_gate.py",
        "tradingbot/adapters/mt5_execution.py",
        "engine/strategies/price_action_strategy.py",
        "tradingbot/domain/gold_strategies/m5_london_sweep.py",
        "tradingbot/domain/gold_strategies/router.py",
        "tradingbot/config/live.py",
        "tradingbot/config/price_action.py",
        "tradingbot/ml/integration/config.py",
        "tradingbot/ml/shadow/shadow_gate.py",
    ]
    modules: list[dict[str, Any]] = []
    extra_edges: list[dict[str, str]] = []
    for rel in key_modules:
        p = ROOT / rel
        rec: dict[str, Any] = {"path": rel, "present": p.is_file()}
        if p.is_file():
            rec.update(_top_level_public(p))
            rec["imports"] = _import_edges(p)
            rec["class"] = _classify_path(rel)
            for imp in rec["imports"]:
                extra_edges.append({"from": rel, "to": imp})
        modules.append(rec)
    live_keys = sorted(k for k in LIVE_TRADING_CONFIG.keys() if "PASSWORD" not in k.upper() and "LOGIN" not in k.upper())

    pa = get_price_action_config("XAUUSD", "M5")
    payload: dict[str, Any] = {
        "phase": "1.5.61",
        "offline_only": True,
        "secrets_not_read": True,
        "inventory": {
            "file_count": len(files),
            "python_files": len(py),
            "by_extension": dict(by_ext.most_common(25)),
            "python_class": dict(classified),
            "package_dirs": packages,
            "test_files": tests,
            "doc_files": docs,
            "todo_fixme": _count_todo(py),
            "scripts": scripts,
            "config_files": config_files,
            "live_config_keys_no_secrets": live_keys,
            "adaptive_in_live_trading_config": "ADAPTIVE_REGIME_ENABLED" in LIVE_TRADING_CONFIG,
        },
        "files": file_records,
        "modules": modules,
        "entry_points": _entry_points(),
        "runtime_paths": {
            "default_live_chain": _live_call_chain(),
            "paper_backtest": "B",
            "shadow": "C",
            "ml_research": "D",
            "isolated_research": "E",
            "test_only": "F",
        },
        "production_components": [
            "tradingbot/kernel/trading_kernel.py",
            "tradingbot/pipeline/*",
            "tradingbot/adapters/multi_engine_router.py",
            "tradingbot/adapters/legacy_strategy_registry.py",
            "engine/strategies/price_action_strategy.py",
            "tradingbot/domain/gold_strategies/m5_london_sweep.py",
            "tradingbot/adapters/risk_gate.py",
            "tradingbot/adapters/mt5_execution.py",
            "tradingbot/adapters/mt5_market_data.py",
            "tradingbot/adapters/mt5_position_manager.py",
            "tradingbot/services/meta_labeler.py",
            "tradingbot/config/live.py",
        ],
        "research_components": [
            "tradingbot/ml/research/**",
            "tradingbot/ml/research/v41_isolated/**",
            "tradingbot/ml/research/pa_live_audit/**",
            "scripts/run_phase*.py",
            "scripts/phase*.py",
        ],
        "configs": {
            "PRIMARY_SYMBOL": PRIMARY_SYMBOL,
            "config_snapshot_scope": "this_audit_process_env_not_running_daemon",
            "PA_PRODUCTION_LOCK": LIVE_TRADING_CONFIG.get("PA_PRODUCTION_LOCK"),
            "MULTI_ENGINE_ROUTER_ENABLED": LIVE_TRADING_CONFIG.get("MULTI_ENGINE_ROUTER_ENABLED"),
            "VOL_REGIME_ENABLED": LIVE_TRADING_CONFIG.get("VOL_REGIME_ENABLED"),
            "ADAPTIVE_REGIME_ENABLED_in_LIVE_TRADING_CONFIG": "ADAPTIVE_REGIME_ENABLED" in LIVE_TRADING_CONFIG,
            "ADAPTIVE_REGIME_ENABLED_get_default_false": bool(LIVE_TRADING_CONFIG.get("ADAPTIVE_REGIME_ENABLED", False)),
            "META_OBSERVER_MODE": LIVE_TRADING_CONFIG.get("META_OBSERVER_MODE"),
            "LOOP_INTERVAL": LIVE_TRADING_CONFIG.get("LOOP_INTERVAL"),
            "RISK_PER_TRADE": LIVE_TRADING_CONFIG.get("RISK_PER_TRADE"),
            "PIPELINE_TIMEOUT_MS": PIPELINE_TIMEOUT_MS,
            "USE_ML_KERNEL_process": is_ml_kernel_enabled(),
            "TREND_MODEL_ID": TREND_MODEL_ID,
            "TREND_ENGINE_ID": TREND_ENGINE_ID,
            "TREND_ENGINE_V41_ID": TREND_ENGINE_V41_ID,
            "resolve_active_trend_engine_id": resolve_active_trend_engine_id(),
            "ACTIVE_STRATEGIES_true": [k for k, v in ACTIVE_STRATEGIES.items() if v],
            "pa_m5_preset": pa.get("PRESET"),
            "pa_m5_mode": pa.get("GOLD_STRATEGY_MODE"),
        },
        "strategies": [
            {
                "id": "priceaction",
                "live": True,
                "implementation": "engine/strategies/price_action_strategy.py + evaluate_m5_london_sweep",
                "activation": "MultiEngineRouter + PA_PRODUCTION_LOCK",
            },
            {
                "id": "VOL_REGIME",
                "live": False,
                "shadow": True,
                "implementation": "VolRegimeStrategyRegistry",
            },
            {
                "id": "ADAPTIVE_REGIME",
                "live": False,
                "shadow": True,
                "implementation": "AdaptiveRegimeStrategyRegistry",
            },
            {
                "id": "trend_rf_v40",
                "live": False,
                "research": True,
                "note": "frozen rollback / calibration owner",
            },
            {
                "id": "trend_rf_v41",
                "live": False,
                "research": True,
                "note": "active ML id if kernel on; class C neutral 1.0",
            },
            {
                "id": "phase9_9",
                "live": False,
                "note": "RANGE engine id; not selected under PA lock",
            },
        ],
        "models": {
            "trend_rf_v40": _bundle_meta("v40"),
            "trend_rf_v41": _bundle_meta("v41"),
        },
        "tests": {"files": tests, "count": len(tests)},
        "documentation": {"files": docs, "count": len(docs)},
        "contradictions": [
            {
                "id": "docs_age",
                "class": "C",
                "note": "docs_v2/01_truth/CURRENT_STATE.md Last Verified 2026-08-22; later v41/PA audits exist",
            },
            {
                "id": "backtest_default_tf",
                "class": "C",
                "note": "BacktestConfig.timeframe default M1 vs live M5",
            },
            {
                "id": "symbol_identity",
                "class": "E",
                "note": "XAUUSD research vs XAUUSD_i live unproven",
            },
            {
                "id": "engine_settings_credential_fallback",
                "class": "D",
                "note": "tradingbot/config/engine_settings.py has hardcoded MT5 fallback defaults — do not document values; env must override",
            },
            {
                "id": "london_sweep_name",
                "class": "C",
                "note": "GOLD_STRATEGY_MODE=london_sweep but live window is NY 15-16 UTC",
            },
            {
                "id": "ml_shadow_default_split",
                "class": "C",
                "note": "is_ml_shadow_enabled defaults false; daemon sets ENABLE_ML_SHADOW=true",
            },
        ],
        "unknowns": [
            {
                "id": "operator_env_overrides",
                "priority": "P0",
                "what": "Whether operator .env overrides daemon defaults",
                "why": ".env not read in this audit (secrets)",
                "resolve": "operator-exported sanitized env dump (no passwords)",
                "requires_mt5": False,
            },
            {
                "id": "xauusd_i_identity",
                "priority": "P0",
                "what": "Economic identity of research XAUUSD vs live XAUUSD_i",
                "why": "No paired tape; order_value diverges",
                "resolve": "broker symbol_info snapshot + bid/ask",
                "requires_mt5": True,
            },
            {
                "id": "round_trip_costs",
                "priority": "P0",
                "what": "Live spread/slip/commission",
                "why": "No class-A tape (1.5.51-55)",
                "resolve": "exported bid/ask + tickets",
                "requires_mt5": True,
            },
            {
                "id": "meta_continuous_enforcement",
                "priority": "P1",
                "what": "Whether meta currently rejects live PA",
                "why": "Gating is conditional; sample in meta_decisions.jsonl is small/historical",
                "resolve": "current-day meta journal",
                "requires_mt5": False,
            },
            {
                "id": "demo_session_bypass",
                "priority": "P1",
                "what": "Whether DEMO_DISABLE_SESSION_FILTER is on",
                "why": "env not inspected",
                "resolve": "sanitized flag dump",
                "requires_mt5": False,
            },
        ],
        "risk_items": [
            "RiskGate.evaluate is mandatory on kernel path",
            "Missing live tick → spread 999 → reject",
            "PA lock prevents VOL/Adaptive selection",
            "v41 calibration remains 1.0",
        ],
        "dependency_edges": [
            {"from": "factory.build_strategy_registry", "to": "MultiEngineRouterRegistry"},
            {"from": "MultiEngineRouterRegistry", "to": "LegacyStrategyRegistry"},
            {"from": "LegacyStrategyRegistry", "to": "PriceActionStrategy"},
            {"from": "PriceActionStrategy", "to": "evaluate_m5_london_sweep"},
            {"from": "TradingKernel", "to": "RiskGate"},
            {"from": "RiskGate", "to": "Mt5ExecutionAdapter"},
            *extra_edges,
        ],
    }

    if write_reports:
        out = ROOT / "data" / "ml" / "reports" / "full_repository_audit"
        out.mkdir(parents=True, exist_ok=True)
        (out / "audit.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        split_keys = (
            "files",
            "modules",
            "entry_points",
            "dependency_edges",
            "runtime_paths",
            "production_components",
            "research_components",
            "configs",
            "strategies",
            "models",
            "tests",
            "documentation",
            "contradictions",
            "unknowns",
            "risk_items",
        )
        for key in split_keys:
            (out / f"{key}.json").write_text(
                json.dumps(payload[key], indent=2, default=str),
                encoding="utf-8",
            )
        slim = {
            "inventory": payload["inventory"],
            "entry_points": payload["entry_points"],
            "configs": payload["configs"],
            "contradictions": payload["contradictions"],
            "unknowns": payload["unknowns"],
        }
        (out / "summary.json").write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
        payload["report_dir"] = str(out)
    return payload


if __name__ == "__main__":
    result = run_full_repo_audit()
    inv = result["inventory"]
    print(
        json.dumps(
            {
                "files": inv["file_count"],
                "python": inv["python_files"],
                "tests": inv["python_class"],
                "todo": inv["todo_fixme"],
                "configs": result["configs"],
                "report_dir": result.get("report_dir"),
            },
            indent=2,
            default=str,
        )
    )
