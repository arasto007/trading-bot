#!/usr/bin/env python3
"""Run Phase 49-51 strict profitability pipeline."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = sys.executable


def main() -> int:
    env = os.environ.copy()
    steps = [
        ([PY, "tradingbot/ml/research/phase49/run_phase49.py"], "Phase 49", env),
        ([PY, "-m", "pytest", "tests/test_phase49_51.py::TestPhase49", "-q"], "Test 49", env),
        ([PY, "tradingbot/ml/research/phase50/run_phase50.py"], "Phase 50", env),
        ([PY, "tradingbot/ml/research/phase50/run_phase50.py"], "Phase 50", env),
        ([PY, "tradingbot/ml/research/phase51/run_phase51.py"], "Phase 51", env),
        ([PY, "-m", "pytest", "tests/test_phase49_51.py", "-q"], "Test 49-51", env),
        ([PY, "tradingbot/ml/research/phase34d/run_engineering_report.py"], "Refresh 34D", env),
    ]
    # remove duplicate phase 50 line
    steps = [
        ([PY, "tradingbot/ml/research/phase49/run_phase49.py"], "Phase 49", env),
        ([PY, "-m", "pytest", "tests/test_phase49_51.py::TestPhase49", "-q"], "Test 49", env),
        ([PY, "tradingbot/ml/research/phase50/run_phase50.py"], "Phase 50", env),
        ([PY, "tradingbot/ml/research/phase51/run_phase51.py"], "Phase 51", env),
        ([PY, "-m", "pytest", "tests/test_phase49_51.py", "-q"], "Test 49-51", env),
        ([PY, "tradingbot/ml/research/phase34d/run_engineering_report.py"], "Refresh 34D", env),
    ]
    for cmd, label, run_env in steps:
        print(f"\n=== {label} ===", flush=True)
        code = subprocess.run(cmd, cwd=ROOT, env=run_env).returncode
        if code != 0:
            print(f"FAILED {label}", flush=True)
            return code
    print("\nPipeline complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
