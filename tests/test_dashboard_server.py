"""Tests for Python local dashboard server (v10)."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "dashboard_server.py"


def _get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _post(url: str, timeout: float = 130.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_dashboard_server_module_exists():
    assert SERVER.is_file()


def test_actions_map_bats_exist():
    import importlib.util

    spec = importlib.util.spec_from_file_location("dashboard_server", SERVER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, spec_d in mod.ACTIONS.items():
        bat = ROOT / str(spec_d["bat"]).replace("/", "\\")
        assert bat.is_file(), f"action {name} missing {bat}"


def test_dashboard_server_http():
    proc = subprocess.Popen(
        [sys.executable, str(SERVER), "--no-browser", "--port", "18766"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                code, body = _get("http://127.0.0.1:18766/api/health")
                if code == 200:
                    break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.3)
        else:
            raise AssertionError("server did not start")

        code, body = _get("http://127.0.0.1:18766/")
        assert code == 200
        assert "SOVEREIGN" in body
        assert "v10.0.0" in body
        assert "onclick" in body

        code, body = _get("http://127.0.0.1:18766/panel")
        assert code == 200
        assert "Aggregate Account Equity" in body or "Equity" in body

        code, data = _post("http://127.0.0.1:18766/api/refresh")
        assert code == 200
        assert data.get("ok") is True
        assert "UTC" in str(data.get("message", ""))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
