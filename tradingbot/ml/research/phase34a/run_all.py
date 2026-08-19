#!/usr/bin/env python3
"""Run all Phase 34 engineering audits in order with tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PY = sys.executable


def run(cmd: list[str], label: str) -> int:
    print(f"\n=== {label} ===", flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    return r.returncode


def main() -> int:
    steps = [
        ([PY, "tradingbot/ml/research/phase34a/run_audit.py"], "Phase 34A Raw ML"),
        ([PY, "-m", "pytest", "tests/test_phase34a.py", "-q"], "Test 34A"),
        ([PY, "tradingbot/ml/research/phase34b/run_label_audit.py"], "Phase 34B Labels"),
        ([PY, "-m", "pytest", "tests/test_phase34b.py", "-q"], "Test 34B"),
        ([PY, "tradingbot/ml/research/phase34c/run_filter_audit.py"], "Phase 34C Filters"),
        ([PY, "-m", "pytest", "tests/test_phase34c.py", "-q"], "Test 34C"),
        ([PY, "tradingbot/ml/research/phase34d/run_engineering_report.py"], "Phase 34D Report"),
        ([PY, "-m", "pytest", "tests/test_phase34c.py::TestPhase34D", "-q"], "Test 34D"),
    ]
    for cmd, label in steps:
        code = run(cmd, label)
        if code != 0:
            print(f"FAILED: {label} (exit {code})", flush=True)
            return code
    print("\nAll Phase 34 steps completed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
