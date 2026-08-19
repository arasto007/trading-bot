"""Phase 17D — regression suite runner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any


def run_regression_suite(
    *,
    project_root: Path,
    test_patterns: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    patterns = test_patterns or (
        "tests/test_phase17d_bundle_promotion.py",
        "tests/test_phase17c_shadow_bundle.py",
        "tests/test_phase15a",
    )
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=no", *patterns]
    proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    passed = failed = 0
    for line in stdout.splitlines():
        if " passed" in line and " in " in line:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p == "passed" and i > 0:
                    try:
                        passed = int(parts[i - 1])
                    except ValueError:
                        pass
        if " failed" in line:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p == "failed" and i > 0:
                    try:
                        failed = int(parts[i - 1])
                    except ValueError:
                        pass

    return {
        "phase": "17D",
        "passed": proc.returncode == 0 and failed == 0,
        "exit_code": proc.returncode,
        "tests_passed": passed,
        "tests_failed": failed,
        "patterns": list(patterns),
        "stdout_tail": stdout[-2000:] if len(stdout) > 2000 else stdout,
        "stderr_tail": stderr[-1000:] if len(stderr) > 1000 else stderr,
    }
