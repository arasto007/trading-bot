#!/usr/bin/env python3
"""One-shot: signal fix + autotrading + smoke trade + start LIVE."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, cmd: list[str]) -> int:
    print(f"\n--- {label} ---")
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    print(f"[exit={proc.returncode}]")
    return proc.returncode


def main() -> int:
    py = sys.executable
    steps = [
        ("pytest vol_regime", [py, "-m", "pytest", "tests/test_vol_regime_registry.py", "-q", "--tb=no"]),
        ("diagnose signals", [py, "scripts/diagnose_vol_regime_signals.py"]),
        ("diagnose autotrading", [py, "scripts/diagnose_autotrading.py"]),
        ("execution check", [py, "scripts/smoke_test_execution.py"]),
    ]
    for label, cmd in steps:
        if run(label, cmd) != 0:
            print(f"\nVERIFY STOPPED at: {label}")
            return 1

    print("\n--- start LIVE daemon ---")
    ps1 = ROOT / "scripts" / "start_live_daemon.ps1"
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(ps1)],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(f"[daemon exit={proc.returncode}]")
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
