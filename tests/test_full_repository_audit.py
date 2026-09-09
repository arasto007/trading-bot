"""Phase 1.5.61 — audit-only checks. Does not start MT5 or the live daemon."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data" / "ml" / "reports" / "full_repository_audit"
SOT = ROOT / "docs_v2" / "01_truth" / "FULL_REPOSITORY_SOURCE_OF_TRUTH.md"

REQUIRED_JSON = (
    "audit.json",
    "files.json",
    "modules.json",
    "entry_points.json",
    "dependency_edges.json",
    "runtime_paths.json",
    "production_components.json",
    "research_components.json",
    "configs.json",
    "strategies.json",
    "models.json",
    "tests.json",
    "documentation.json",
    "contradictions.json",
    "unknowns.json",
    "risk_items.json",
    "summary.json",
)

SOT_SECTIONS = (
    "1. Executive summary",
    "2. Repository map",
    "3. Runtime entry points",
    "4. Default live execution chain",
    "5. Production vs research boundary",
    "6. Configuration truth",
    "7. Strategy truth",
    "8. ML truth",
    "9. Risk truth",
    "10. Execution truth",
    "11. Data / feature truth",
    "12. Test truth",
    "13. Documentation truth",
    "14. Known contradictions",
    "15. Critical unknowns",
    "16. Recommended next investigation areas",
)

LIVE_CHAIN_FILES = (
    "scripts/start_bot.py",
    "scripts/start_live_daemon.ps1",
    "scripts/run_live_watchdog.py",
    "tradingbot/__main__.py",
    "tradingbot/application/live_runner.py",
    "tradingbot/application/bootstrap.py",
    "tradingbot/ml/integration/factory.py",
    "tradingbot/adapters/multi_engine_router.py",
    "tradingbot/adapters/legacy_strategy_registry.py",
    "engine/strategies/price_action_strategy.py",
    "tradingbot/domain/gold_strategies/router.py",
    "tradingbot/domain/gold_strategies/m5_london_sweep.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/mt5_execution.py",
)


def test_run_audit_writes_required_json() -> None:
    from tradingbot.ml.research.full_repo_audit.run import run_full_repo_audit

    payload = run_full_repo_audit(write_reports=True)
    assert payload["offline_only"] is True
    assert payload["secrets_not_read"] is True
    for name in REQUIRED_JSON:
        path = REPORT_DIR / name
        assert path.is_file(), name
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data is not None


def test_audit_json_has_required_keys() -> None:
    from tradingbot.ml.research.full_repo_audit.run import run_full_repo_audit

    payload = run_full_repo_audit(write_reports=True)
    for key in (
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
    ):
        assert key in payload, key
    assert payload["inventory"]["file_count"] > 0
    assert payload["inventory"]["python_files"] > 0
    assert any(e["id"] == "default_live_daemon" for e in payload["entry_points"])


def test_sot_document_has_required_sections() -> None:
    text = SOT.read_text(encoding="utf-8")
    for section in SOT_SECTIONS:
        assert section in text, section
    assert "python -m tradingbot --loop --execute" in text
    assert "XAUUSD_i" in text
    assert "trend_rf_v41" in text
    assert "trend_rf_v40" in text


def test_live_chain_files_exist() -> None:
    for rel in LIVE_CHAIN_FILES:
        assert (ROOT / rel).is_file(), rel


def test_production_invariants_unchanged() -> None:
    from tradingbot.config.live import LIVE_TRADING_CONFIG, PRIMARY_SYMBOL
    from tradingbot.config.strategies import ACTIVE_STRATEGIES
    from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID
    from tradingbot.ml.integration.kernel_adapter import PIPELINE_TIMEOUT_MS
    from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    assert PRIMARY_SYMBOL == "XAUUSD_i"
    assert LIVE_TRADING_CONFIG.get("PA_PRODUCTION_LOCK") is True
    assert LIVE_TRADING_CONFIG.get("MULTI_ENGINE_ROUTER_ENABLED") is True
    assert PIPELINE_TIMEOUT_MS == 500.0
    assert TREND_MODEL_ID == "trend_rf_v40"
    assert TREND_ENGINE_ID == "trend_rf_v40"
    assert TREND_ENGINE_V41_ID == "trend_rf_v41"
    assert resolve_active_trend_engine_id() == "trend_rf_v41"
    assert ACTIVE_STRATEGIES.get("priceaction") is True
    assert sum(1 for v in ACTIVE_STRATEGIES.values() if v) == 1


def test_json_does_not_leak_secrets() -> None:
    from tradingbot.ml.research.full_repo_audit.run import run_full_repo_audit

    payload = run_full_repo_audit(write_reports=True)
    blob = json.dumps(payload, default=str).lower()
    for banned in ("mt5_password", "email_password", "amir@"):
        assert banned not in blob
    cfg = payload["configs"]
    assert "MT5_PASSWORD" not in cfg
    assert "MT5_LOGIN" not in cfg


def test_modules_ast_extracted() -> None:
    from tradingbot.ml.research.full_repo_audit.run import run_full_repo_audit

    payload = run_full_repo_audit(write_reports=False)
    by_path = {m["path"]: m for m in payload["modules"]}
    factory = by_path["tradingbot/ml/integration/factory.py"]
    assert factory["present"] is True
    assert "build_strategy_registry" in factory["functions"]
    risk = by_path["tradingbot/adapters/risk_gate.py"]
    assert "RiskGate" in risk["classes"]
