"""Phase 1.5.62 — documentation system audit tests (offline)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "ml" / "reports" / "documentation_system_audit"


def test_documentation_system_audit_writes_json() -> None:
    from tradingbot.ml.research.documentation_system_audit.run import (
        CANONICAL_ENTRY,
        run_documentation_system_audit,
    )

    payload = run_documentation_system_audit(write_reports=True)
    assert payload["canonical_entry"] == CANONICAL_ENTRY
    assert payload["rules"]["one_canonical_entry"] is True
    assert payload["rules"]["do_not_read_dotenv_secrets"] is True
    assert payload["counts"]["markdown_files"] > 50
    for name in ("audit.json", "files.json", "canonical.json"):
        path = REPORT / name
        assert path.is_file(), name
        json.loads(path.read_text(encoding="utf-8"))


def test_audit_document_exists() -> None:
    path = ROOT / "docs_v2" / "01_truth" / "DOCUMENTATION_SYSTEM_AUDIT.md"
    text = path.read_text(encoding="utf-8")
    assert "proposed hierarchy" in text.lower() or "Proposed hierarchy" in text
    assert "PROJECT_SOURCE_OF_TRUTH.md" in text
    assert "Do not delete" in text or "do not delete" in text.lower()
