"""Documentation memory hardening v2 tests. Offline. No production runtime imports."""

from __future__ import annotations

import json
from pathlib import Path

from tradingbot.ml.research.documentation_freshness.scanner import (
    SNAPSHOT,
    WATCHED,
    scan_freshness,
    write_snapshot,
)
from tradingbot.ml.research.documentation_memory_hardening_v2.load_path import (
    OWNERS,
    classify_questions,
    corpus,
    hallucination_guards,
)
from tradingbot.ml.research.documentation_memory_hardening_v2.run import (
    REQUIRED_OWNERS,
    WATCH_CLASSIFICATIONS,
    run_hardening_v2,
)

ROOT = Path(__file__).resolve().parents[1]


def test_hardening_v2_runner_ok() -> None:
    payload = run_hardening_v2(write_reports=True)
    assert payload["production_source_read"] is False
    assert payload["bootstrap_imports_research"] is False
    assert payload["canonical_entry_count"] == 1
    assert payload["required_watch_missing_from_WATCHED"] == []
    assert payload["ownership"]["ok"] is True
    assert payload["impact_map"]["ok"] is True
    assert payload["question_failures"] == [], payload["question_failures"]
    assert payload["hallucination_failures"] == [], payload["hallucination_failures"]
    assert payload["ok"] is True
    assert (ROOT / "data/ml/reports/documentation_memory_hardening_v2/verification.json").is_file()
    assert (ROOT / "data/ml/reports/documentation_memory_hardening_v2/watched_code_audit.json").is_file()


def test_canonical_entry_unique() -> None:
    found = []
    for p in (ROOT / "docs_v2").rglob("*.md"):
        if "Canonical-Entry:** true" in p.read_text(encoding="utf-8"):
            found.append(p.relative_to(ROOT).as_posix())
    assert found == ["docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"]


def test_duplicate_canonical_entry_finding(tmp_path: Path) -> None:
    docs = tmp_path / "docs_v2" / "01_truth"
    docs.mkdir(parents=True)
    marker = "**Canonical-Entry:** true\n**Status:** VERIFIED\n**Last verified:** 2026-09-01\n"
    (docs / "a.md").write_text(marker + "XAUUSD_i 999 gold_ny_sweep USE_ML_KERNEL\n", encoding="utf-8")
    (docs / "b.md").write_text(marker, encoding="utf-8")
    (tmp_path / "w.py").write_text("x=1\n", encoding="utf-8")
    fixture = tmp_path / "snap.json"
    write_snapshot(path=fixture, baseline_kind="test_fixture", watched=["w.py"], root=tmp_path)
    result = scan_freshness(
        snapshot_path=fixture,
        watched=["w.py"],
        root=tmp_path,
        canonical_docs=["docs_v2/01_truth/a.md"],
        check_docs=True,
    )
    assert any(f.get("id") == "duplicate_canonical_entry" for f in result["findings"])


def test_missing_owner_and_broken_owner_paths() -> None:
    missing = [rel for rel in REQUIRED_OWNERS.values() if not (ROOT / rel).is_file()]
    assert missing == []


def test_fresh_session_load_path_without_production() -> None:
    from tradingbot.ml.research.documentation_memory_hardening_v2.load_path import (
        FULL_SESSION_OWNERS,
    )

    blob, files = corpus(FULL_SESSION_OWNERS)
    assert "tradingbot/config/live.py" not in files
    assert "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md" in files
    questions = classify_questions(blob, owners_loaded=FULL_SESSION_OWNERS)
    assert all(q["ok"] for q in questions), [q for q in questions if not q["ok"]]
    boundary = next(q for q in questions if q["id"] == "Q_boundary")
    assert boundary["classification"] == "DOCUMENTED"
    sl = next(q for q in questions if q["id"] == "Q_sl_tp")
    assert sl["classification"] == "DOCUMENTED"
    env = next(q for q in questions if q["id"] == "Q_unknown_env")
    assert env["classification"] == "UNKNOWN"
    cx = next(q for q in questions if q["id"] == "Q_contradiction")
    assert cx["classification"] == "CONTRADICTED"
    daemon = next(q for q in questions if q["id"] == "Q_daemon_now")
    assert daemon["classification"] == "UNKNOWN"
    guards = hallucination_guards(blob)
    assert all(g["ok"] for g in guards), guards


def test_sl_tp_without_pa_owner_is_derived_not_hallucinated() -> None:
    blob, _ = corpus(())
    questions = classify_questions(blob, owners_loaded=())
    sl = next(q for q in questions if q["id"] == "Q_sl_tp")
    assert sl["expected"] == "DERIVED"
    assert sl["ok"] is True
    assert "SL_ATR_MULT" not in blob or "PRICE_ACTION_LIVE_SPEC" in blob


def test_unknown_not_represented_as_fact() -> None:
    blob, _ = corpus(("UNKNOWN", "SAFETY"))
    guards = hallucination_guards(blob)
    assert all(g["ok"] for g in guards), guards
    assert "Operator-effective state: UNKNOWN" in blob or "UNKNOWN" in blob
    assert "## 2. Current live system" not in blob


def test_historical_docs_not_marked_current_owners() -> None:
    current_state = (ROOT / "docs_v2/01_truth/CURRENT_STATE.md").read_text(encoding="utf-8")
    source = (ROOT / "docs_v2/01_truth/SOURCE_OF_TRUTH.md").read_text(encoding="utf-8")
    startup = (ROOT / "docs_v2/03_runtime/STARTUP.md").read_text(encoding="utf-8")
    for text in (current_state, source, startup):
        assert "SUPERSEDED" in text or "HISTORICAL" in text


def test_research_not_imported_by_live_bootstrap() -> None:
    text = (ROOT / "tradingbot/application/bootstrap.py").read_text(encoding="utf-8")
    assert "ml.research" not in text
    assert "documentation_freshness" not in text
    assert "documentation_consistency" not in text
    assert "documentation_memory_hardening" not in text


def test_watched_files_mapped_or_explicit_gap() -> None:
    impact = (ROOT / "docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md").read_text(
        encoding="utf-8"
    )
    missing = [rel for rel in WATCHED if f"`{rel}`" not in impact]
    assert missing == [], missing
    watch_must = [row["path"] for row in WATCH_CLASSIFICATIONS if row["decision"] == "WATCH"]
    assert all(p in WATCHED for p in watch_must)
    assert any(row["decision"] == "UNKNOWN" for row in WATCH_CLASSIFICATIONS)
    assert any(row["decision"] == "DO_NOT_WATCH" for row in WATCH_CLASSIFICATIONS)
    assert any(row["decision"] == "RESEARCH_ONLY" for row in WATCH_CLASSIFICATIONS)


def test_canonical_snapshot_not_mutated_by_hardening_tests(tmp_path: Path) -> None:
    before = SNAPSHOT.read_bytes()
    write_snapshot(path=tmp_path / "s.json", baseline_kind="test_fixture")
    scan_freshness(snapshot_path=tmp_path / "s.json")
    run_hardening_v2(write_reports=True)
    assert SNAPSHOT.read_bytes() == before


def test_owner_docs_have_epistemic_role() -> None:
    for rel in REQUIRED_OWNERS.values():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Epistemic-Role:" in text, rel
        assert "**Last verified:**" in text or "Last verified" in text, rel


def test_handoff_contract_lists_required_fields() -> None:
    text = (ROOT / "docs_v2/99_change_control/CHATGPT_CURSOR_WORKFLOW.md").read_text(
        encoding="utf-8"
    )
    for field in (
        "VERDICT",
        "SCOPE",
        "FILES INSPECTED",
        "FILES MODIFIED",
        "PRODUCTION FILES MODIFIED?",
        "DOCUMENTATION FILES MODIFIED?",
        "TESTS",
        "FRESHNESS STATUS",
        "CONSISTENCY STATUS",
        "UNKNOWNs",
        "CONTRADICTIONS",
        "SAFETY CHECKS",
        "GIT STATUS",
        "EXACT NEXT RECOMMENDATION",
        "AFFECTED DOMAIN",
        "OWNER DOC",
        "DERIVED DOCS",
    ):
        assert field in text, field


def test_hardening_v2_doc_answers_contract_questions() -> None:
    text = (ROOT / "docs_v2/01_truth/DOCUMENTATION_MEMORY_HARDENING_V2.md").read_text(
        encoding="utf-8"
    )
    for needle in (
        "PROJECT_SOURCE_OF_TRUTH.md",
        "CHATGPT_BOOTSTRAP.md",
        "SHA-256",
        "UNKNOWN",
        "CONTRADICTION",
        "DERIVED",
        "Operator-effective state",
        "deliberately excluded",
    ):
        assert needle in text, needle


def test_load_path_module_does_not_import_production() -> None:
    src = (ROOT / "tradingbot/ml/research/documentation_memory_hardening_v2/load_path.py").read_text(
        encoding="utf-8"
    )
    assert "from tradingbot.config" not in src
    assert "from tradingbot.adapters" not in src
    assert "from tradingbot.ml.integration" not in src
    for key, rel in OWNERS.items():
        assert (ROOT / rel).is_file(), key


def test_canonical_snapshot_kind_not_test_fixture() -> None:
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert payload.get("baseline_kind") in {"canonical", "explicit_regeneration"}
    assert payload.get("baseline_kind") != "test_fixture"
    assert set(payload["evidence_revision"]) == set(WATCHED)
