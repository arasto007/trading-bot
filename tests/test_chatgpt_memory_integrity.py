"""Phase 1.5.78 — ChatGPT memory integrity. Reads documentation only."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_memory_integrity_docs_only() -> None:
    from tradingbot.ml.research.documentation_memory_hardening import memory_integrity as mi

    src = Path(mi.__file__).read_text(encoding="utf-8")
    assert "from tradingbot.config" not in src
    assert "from tradingbot.adapters" not in src
    assert "from tradingbot.ml.integration" not in src
    result = mi.run_memory_integrity(write_reports=True)
    assert result["production_source_read"] is False
    assert "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md" in result["files_read"]
    assert "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md" in result["files_read"]
    gaps = result["gaps"]
    assert gaps == [], gaps
    assert result["ok"] is True
    report = (ROOT / "docs_v2" / "01_truth" / "CHATGPT_MEMORY_INTEGRITY.md").read_text(encoding="utf-8")
    assert "DOCUMENTATION_GAP" in report
    assert "Production source used in the test:** **NO" in report or "Production source used" in report
