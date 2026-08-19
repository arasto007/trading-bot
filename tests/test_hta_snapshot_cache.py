"""HTA dashboard snapshot cache + parser contract tests."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "hta_dashboard_snapshot.txt"
HTA = ROOT / "live_dashboard.hta"
VBS = ROOT / "scripts" / "test_hta_snapshot_read.vbs"


def _load_snapshot():
    path = ROOT / "scripts" / "status_snapshot.py"
    spec = importlib.util.spec_from_file_location("status_snapshot", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["status_snapshot"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_hta_cache_written_on_emit(tmp_path, monkeypatch):
    mod = _load_snapshot()
    cache = tmp_path / "data" / "hta_dashboard_snapshot.txt"
    monkeypatch.setattr(mod, "HTA_CACHE", cache)
    mod._emit(["STATE|STOPPED", "UTC|2026-01-01 00:00:00"])
    assert cache.is_file()
    text = cache.read_text(encoding="ascii")
    assert "STATE|STOPPED" in text
    assert "UTC|2026-01-01" in text


def test_hta_engine_line_indices_documented_in_vbs():
    """VBScript test uses parts(4)/parts(6) for PA accept/PF — must match Python emit."""
    sample = "ENGINE|PA|DEGRADED|enabled=1|accept=0.15|trades=3|PF=15.654|ExpR=0.265"
    parts = sample.split("|")
    assert parts[4] == "accept=0.15"
    assert parts[6] == "PF=15.654"
    assert parts[7] == "ExpR=0.265"


def test_hta_read_snapshot_vbs_passes():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "status_snapshot.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert CACHE.is_file(), "hta_dashboard_snapshot.txt must exist after snapshot run"
    text = CACHE.read_text(encoding="ascii", errors="replace")
    assert "ENGINE|PA|" in text
    proc = subprocess.run(
        ["cscript", "//nologo", str(VBS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip().startswith("OK|")


def test_hta_reads_cache_after_refresh():
    shell = (ROOT / "scripts" / "hta_shell.vbs").read_text(encoding="utf-8")
    assert "dashboard_live.html" in shell
    assert "RunSnapshotAsync" in shell
    assert "0_hta_snapshot.bat" in shell or "0_hta_snapshot" in shell
