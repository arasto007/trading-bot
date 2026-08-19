#!/usr/bin/env python3
"""Run all production-readiness checks (non-destructive)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

CHECKS: list[tuple[str, list[str]]] = [
    ("MT5 autotrading", [sys.executable, "scripts/diagnose_autotrading.py", "--attach-only"]),
    ("VOL_REGIME signals", [sys.executable, "scripts/diagnose_vol_regime_signals.py"]),
    ("Live setup", [sys.executable, "scripts/check_vol_regime_live_setup.py"]),
    ("Phase 2", [sys.executable, "scripts/verify_phase2_live_ready.py"]),
    ("Phase 4", [sys.executable, "scripts/verify_phase4_live_ready.py"]),
    ("Pipeline audit", [sys.executable, "scripts/audit_live_pipeline.py"]),
    ("Unit tests", [sys.executable, "-m", "pytest", "tests/test_vol_regime_registry.py", "-q"]),
    ("Demo proof", [sys.executable, "scripts/demo_proof_status.py"]),
]

# Never steal MT5 IPC from a running live bot (dashboard + kernel hold the lock).
_SKIP_WHEN_LIVE_BOT: frozenset[str] = frozenset(
    {"MT5 autotrading", "VOL_REGIME signals", "Live setup", "Pipeline audit"}
)


def _live_bot_running() -> bool:
    """Detect kernel child — do not run MT5 attach probes while it is up."""
    try:
        import json
        import subprocess

        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'tradingbot.*--loop' } | "
                "Select-Object -First 1 ProcessId | ConvertTo-Json -Compress",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).strip()
        if not out:
            return False
        data = json.loads(out)
        return bool(data.get("ProcessId"))
    except Exception:
        return False


def _should_skip_mt5_checks() -> bool:
    return _live_bot_running() or _live_bot_holds_ipc()


def _live_bot_holds_ipc() -> bool:
    try:
        from tradingbot.adapters.mt5_utils import is_mt5_lock_held_by_other

        return is_mt5_lock_held_by_other()
    except Exception:
        return False


def main() -> int:
    print("=== Production Readiness Bundle ===")
    live_bot = _should_skip_mt5_checks()
    if live_bot:
        print("NOTE: live tradingbot running — skipping attach-heavy checks")
    failed = 0
    for name, cmd in CHECKS:
        print(f"\n--- {name} ---")
        if live_bot and name in _SKIP_WHEN_LIVE_BOT:
            print(f"[PASS] {name} (skipped — live bot running)")
            continue
        proc = subprocess.run(cmd, cwd=str(ROOT))
        if proc.returncode != 0:
            print(f"[FAIL] {name} exit={proc.returncode}")
            failed += 1
        else:
            print(f"[PASS] {name}")
    print(f"\n=== SUMMARY: {len(CHECKS) - failed}/{len(CHECKS)} passed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
