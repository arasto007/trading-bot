"""Dashboard live HTML generation tests."""
from __future__ import annotations

from pathlib import Path

from scripts.generate_dashboard_live_html import build_html, write_dashboard_live_html

ROOT = Path(__file__).resolve().parents[1]


def test_build_html_contains_equity():
    lines = [
        "STATE|RUNNING",
        "UTC|2026-08-10 12:00:00",
        "ACCOUNT|694.32|694.32|-",
        "ENGINE|PA|DEGRADED|x|accept=0.15|trades=3|PF=15.6|ExpR=0.26",
    ]
    html = build_html(lines)
    assert "694.32" in html
    assert "RUNNING" in html
    assert "v9.1.0" in html


def test_write_dashboard_live_html(tmp_path: Path):
    lines = ["STATE|RUNNING", "UTC|t", "ACCOUNT|1|2|3"]
    out = write_dashboard_live_html(lines, tmp_path)
    assert out.is_file()
    assert out.stat().st_size > 200
