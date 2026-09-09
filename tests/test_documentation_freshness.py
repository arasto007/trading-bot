"""Phase documentation-freshness tests. Must not mutate the canonical snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingbot.ml.research.documentation_freshness.scanner import (
    SNAPSHOT,
    WATCHED,
    current_evidence_revision,
    scan_freshness,
    write_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_snapshot_is_not_rewritten_by_fixture_writes(tmp_path: Path) -> None:
    before = SNAPSHOT.read_bytes() if SNAPSHOT.is_file() else None
    fixture = tmp_path / "snapshot.json"
    write_snapshot(path=fixture, baseline_kind="test_fixture")
    scan_freshness(snapshot_path=fixture)
    after = SNAPSHOT.read_bytes() if SNAPSHOT.is_file() else None
    assert before == after
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["baseline_kind"] == "test_fixture"


def test_write_snapshot_refuses_canonical_without_allow() -> None:
    with pytest.raises(RuntimeError, match="allow_canonical"):
        write_snapshot()
    with pytest.raises(RuntimeError, match="allow_canonical"):
        write_snapshot(path=SNAPSHOT, baseline_kind="explicit_regeneration")
    with pytest.raises(RuntimeError, match="test_fixture"):
        write_snapshot(path=SNAPSHOT, baseline_kind="test_fixture", allow_canonical=True)


def test_modifying_watched_file_causes_stale(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    src = tmp_path / watched_rel
    src.write_text("alpha = 1\n", encoding="utf-8")
    fixture = tmp_path / "snapshot.json"
    write_snapshot(
        path=fixture,
        baseline_kind="test_fixture",
        watched=[watched_rel],
        root=tmp_path,
    )
    src.write_text("alpha = 2\n", encoding="utf-8")
    result = scan_freshness(
        snapshot_path=fixture,
        watched=[watched_rel],
        root=tmp_path,
        check_docs=False,
    )
    assert result["status"] == "STALE"
    assert any(f.get("id") == "code_revision_changed" for f in result["findings"])
    again = scan_freshness(
        snapshot_path=fixture,
        watched=[watched_rel],
        root=tmp_path,
        check_docs=False,
    )
    assert again["status"] == "STALE"
    assert json.loads(fixture.read_text(encoding="utf-8"))["evidence_revision"][
        watched_rel
    ] != current_evidence_revision(watched=[watched_rel], root=tmp_path)[watched_rel]


def test_running_scan_does_not_erase_stale(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    src = tmp_path / watched_rel
    src.write_text("x = 1\n", encoding="utf-8")
    fixture = tmp_path / "snapshot.json"
    write_snapshot(path=fixture, baseline_kind="test_fixture", watched=[watched_rel], root=tmp_path)
    src.write_text("x = 2\n", encoding="utf-8")
    first = scan_freshness(
        snapshot_path=fixture, watched=[watched_rel], root=tmp_path, check_docs=False
    )
    second = scan_freshness(
        snapshot_path=fixture, watched=[watched_rel], root=tmp_path, check_docs=False
    )
    assert first["status"] == "STALE"
    assert second["status"] == "STALE"


def test_missing_snapshot_is_unknown_not_pass(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    (tmp_path / watched_rel).write_text("ok\n", encoding="utf-8")
    result = scan_freshness(
        snapshot_path=tmp_path / "missing.json",
        watched=[watched_rel],
        root=tmp_path,
        check_docs=False,
    )
    assert result["status"] == "UNKNOWN"
    assert any(f.get("id") == "no_snapshot" for f in result["findings"])


def test_missing_watched_source_is_broken(tmp_path: Path) -> None:
    fixture = tmp_path / "snapshot.json"
    write_snapshot(
        path=fixture,
        baseline_kind="test_fixture",
        watched=["present.py"],
        root=tmp_path,
    )
    (tmp_path / "present.py").write_text("ok\n", encoding="utf-8")
    result = scan_freshness(
        snapshot_path=fixture,
        watched=["missing_watched.py"],
        root=tmp_path,
        check_docs=False,
    )
    assert result["status"] == "BROKEN"
    assert any(f.get("id") == "missing_watched_source" for f in result["findings"])


def test_deleted_watched_source_is_broken(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    src = tmp_path / watched_rel
    src.write_text("ok\n", encoding="utf-8")
    fixture = tmp_path / "snapshot.json"
    write_snapshot(path=fixture, baseline_kind="test_fixture", watched=[watched_rel], root=tmp_path)
    src.unlink()
    result = scan_freshness(
        snapshot_path=fixture, watched=[watched_rel], root=tmp_path, check_docs=False
    )
    assert result["status"] == "BROKEN"
    assert any(f.get("id") == "deleted_watched_source" for f in result["findings"])


def test_doc_only_change_does_not_create_code_stale(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    (tmp_path / watched_rel).write_text("ok\n", encoding="utf-8")
    docs = tmp_path / "docs_v2" / "01_truth"
    docs.mkdir(parents=True)
    (docs / "note.md").write_text("before\n", encoding="utf-8")
    fixture = tmp_path / "snapshot.json"
    write_snapshot(path=fixture, baseline_kind="test_fixture", watched=[watched_rel], root=tmp_path)
    (docs / "note.md").write_text("after\n", encoding="utf-8")
    result = scan_freshness(
        snapshot_path=fixture, watched=[watched_rel], root=tmp_path, check_docs=False
    )
    assert result["status"] == "PASS"


def test_changed_source_unchanged_docs_is_stale(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    src = tmp_path / watched_rel
    src.write_text("v1\n", encoding="utf-8")
    fixture = tmp_path / "snapshot.json"
    write_snapshot(path=fixture, baseline_kind="test_fixture", watched=[watched_rel], root=tmp_path)
    src.write_text("v2\n", encoding="utf-8")
    result = scan_freshness(
        snapshot_path=fixture, watched=[watched_rel], root=tmp_path, check_docs=False
    )
    assert result["status"] == "STALE"


def test_explicit_baseline_regeneration_is_distinguishable(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    (tmp_path / watched_rel).write_text("ok\n", encoding="utf-8")
    fixture = tmp_path / "snapshot.json"
    write_snapshot(
        path=fixture,
        baseline_kind="explicit_regeneration",
        watched=[watched_rel],
        root=tmp_path,
        note="operator-explicit regeneration",
    )
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["baseline_kind"] == "explicit_regeneration"
    assert payload["baseline_kind"] != "test_fixture"


def test_canonical_freshness_scan_does_not_write() -> None:
    before = SNAPSHOT.read_bytes()
    result = scan_freshness()
    after = SNAPSHOT.read_bytes()
    assert before == after
    assert result["stale_if_code_revision_changes"] is True
    assert len(result["canonical_entry_files"]) == 1
    assert result["watched_count"] == len(WATCHED)
    assert result["status"] in {"PASS", "STALE", "UNKNOWN", "CONTRADICTED", "BROKEN"}


def test_watched_production_files_exist() -> None:
    rev = current_evidence_revision()
    assert "tradingbot/adapters/risk_gate.py" in rev
    assert "tradingbot/ml/integration/factory.py" in rev
    assert "tradingbot/domain/gold_strategies/router.py" in rev
    assert "tradingbot/ml/confidence_engine/calibration_policy.py" in rev
    assert "start/START_BOT.bat" in rev
    assert "tradingbot/__main__.py" in rev
    assert len(rev) == len(WATCHED)
    assert len(rev) >= 30
    from tradingbot.ml.research.documentation_freshness.scanner import DO_NOT_WATCH, WATCH_REASONS

    assert set(WATCH_REASONS) == set(WATCHED)
    assert any(x["class"] == "RESEARCH_ONLY" for x in DO_NOT_WATCH)


def test_documentation_changed_is_warn_not_code_stale(tmp_path: Path) -> None:
    watched_rel = "watched_prod.py"
    (tmp_path / watched_rel).write_text("ok\n", encoding="utf-8")
    docs = tmp_path / "docs_v2" / "01_truth"
    docs.mkdir(parents=True)
    rel_doc = "docs_v2/01_truth/note.md"
    (tmp_path / rel_doc).write_text("before\n", encoding="utf-8")
    fixture = tmp_path / "snapshot.json"
    write_snapshot(
        path=fixture,
        baseline_kind="test_fixture",
        watched=[watched_rel],
        canonical_docs=[rel_doc],
        root=tmp_path,
    )
    (tmp_path / rel_doc).write_text("after\n", encoding="utf-8")
    result = scan_freshness(
        snapshot_path=fixture,
        watched=[watched_rel],
        canonical_docs=[rel_doc],
        root=tmp_path,
        check_docs=False,
    )
    assert result["status"] == "PASS"
    assert any(f.get("id") == "documentation_changed" for f in result["findings"])
    assert not any(f.get("id") == "code_revision_changed" for f in result["findings"])
