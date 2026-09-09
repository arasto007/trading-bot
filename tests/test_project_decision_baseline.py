"""Project decision baseline tests. Offline. Does not rewrite freshness snapshots."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
BOOT = ROOT / "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md"
BASELINE = ROOT / "docs_v2/01_truth/PROJECT_DECISION_BASELINE.md"
JSON_PATH = ROOT / "data/ml/reports/project_decision_baseline/baseline.json"
CX = ROOT / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
SNAPSHOT = ROOT / "data/ml/reports/documentation_freshness/snapshot.json"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_entry_remains_unique() -> None:
    found = []
    for p in (ROOT / "docs_v2").rglob("*.md"):
        if "Canonical-Entry:** true" in p.read_text(encoding="utf-8"):
            found.append(p.relative_to(ROOT).as_posix())
    assert found == ["docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"]
    assert "Canonical-Entry:** true" not in _text(BASELINE)
    assert "**Canonical-Entry:** false" in _text(BASELINE)


def test_baseline_and_bootstrap_exist() -> None:
    assert BASELINE.is_file()
    assert BOOT.is_file()
    assert ENTRY.is_file()
    assert JSON_PATH.is_file()


def test_demo_real_symbol_mapping_not_automatic_contradiction() -> None:
    baseline = _text(BASELINE)
    cx = _text(CX)
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert payload["demo_symbol"] == "XAUUSD_i"
    assert payload["real_symbol"] == "XAUUSD"
    assert payload["symbol_naming"]["automatic_identity_contradiction"] is False
    assert payload["symbol_naming"]["economic_equivalence"] == "UNKNOWN"
    assert "XAUUSD_i" in baseline and "XAUUSD" in baseline
    assert "USER-PROVIDED FACT" in baseline
    assert "DEMO/REAL" in baseline or "DEMO/REAL" in cx
    assert "automatic identity contradiction" in cx.lower()
    assert "NOT PROVEN" in baseline or "economic_equivalence" in JSON_PATH.read_text(encoding="utf-8")
    # Name difference must not be treated as the contradiction itself.
    assert "Naming (USER-PROVIDED FACT)" in cx
    assert "Economics: OPEN" in cx or "economics OPEN" in baseline.lower()


def test_live_pa_ml_v41_lock() -> None:
    baseline = _text(BASELINE)
    assert "priceaction" in baseline
    assert "gold_ny_sweep" in baseline
    assert "USE_ML_KERNEL" in baseline or "ML kernel" in baseline.lower() or "ml_status" in json.loads(
        JSON_PATH.read_text(encoding="utf-8")
    )
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert payload["ml_status"]["USE_ML_KERNEL_default"] is False
    assert payload["v41_status"]["class"] == "C"
    assert float(payload["v41_status"]["calibration_factor"]) == 1.0
    assert payload["v41_status"]["active"] is False
    assert payload["pa_production_lock_default"] is True
    assert "PA_PRODUCTION_LOCK" in _text(BOOT) or "PA lock" in baseline


def test_research_not_imported_by_live_bootstrap() -> None:
    text = (ROOT / "tradingbot/application/bootstrap.py").read_text(encoding="utf-8")
    assert "ml.research" not in text
    assert "documentation_freshness" not in text
    assert "project_decision_baseline" not in text


def test_baseline_has_no_secrets() -> None:
    blob = _text(BASELINE) + JSON_PATH.read_text(encoding="utf-8")
    for needle in ("PASSWORD", "password=", "MT5_PASSWORD", "api_key", "API_KEY", "BEGIN RSA"):
        assert needle not in blob
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert payload["secrets_included"] is False


def test_code_default_vs_operator_state() -> None:
    baseline = _text(BASELINE)
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert "CODE DEFAULT" in baseline
    assert "OPERATOR EFFECTIVE STATE" in baseline or "Operator-effective state" in baseline
    assert payload["operator_effective_state"] == "UNKNOWN"
    assert "operator `.env` is UNKNOWN" in baseline.lower() or "UNK-001" in baseline
    assert ".env" in baseline and "UNKNOWN" in baseline
    assert "round-trip" in baseline.lower() or "UNK-003" in baseline
    assert "costs" in baseline.lower()


def test_hierarchy_and_limits() -> None:
    baseline = _text(BASELINE)
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert "CODE > CANONICAL DOCS" in baseline
    assert payload["full_repository_knowledge_claimed"] is False
    assert "does **not** claim full repository knowledge" in baseline or "not claim full repository" in baseline.lower()
    assert payload["production_ready"] is False
    assert "Production-ready?" in baseline or "production readiness" in baseline.lower()
    assert payload["mt5_live_activation_authorized"] is False
    assert "Must NOT Be Done Yet" in baseline or "must not" in baseline.lower()
    assert "start MT5" in baseline.lower() or "Start MT5" in baseline


def test_major_claims_have_evidence_references() -> None:
    baseline = _text(BASELINE)
    for needle in (
        "live.py::PRIMARY_SYMBOL",
        "factory.py::build_strategy_registry",
        "is_pa_production_lock",
        "RiskGate.evaluate",
        "order_logic.py::order_value",
        "PRICE_ACTION_LIVE_SPEC.md",
        "CHATGPT_CURSOR_WORKFLOW.md",
    ):
        assert needle in baseline, needle


def test_tests_do_not_rewrite_canonical_snapshot() -> None:
    before = SNAPSHOT.read_bytes() if SNAPSHOT.is_file() else None
    assert BASELINE.is_file()
    after = SNAPSHOT.read_bytes() if SNAPSHOT.is_file() else None
    assert before == after
