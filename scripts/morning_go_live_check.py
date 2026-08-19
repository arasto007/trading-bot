#!/usr/bin/env python3
"""Morning pre-flight before starting live trading — run with MT5 already open."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def _mt5_running() -> bool:
    from tradingbot.adapters.mt5_utils import _is_terminal_process_running

    return _is_terminal_process_running()


def _bot_running() -> bool:
    try:
        import json

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
        return bool(json.loads(out).get("ProcessId"))
    except Exception:
        return False


def _run(name: str, cmd: list[str]) -> int:
    print(f"\n--- {name} ---")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    return proc.returncode


def main() -> int:
    print("=" * 50)
    print("  MORNING GO LIVE CHECK")
    print("=" * 50)
    print("\nPrerequisite: MT5 open, logged in, Algo Trading GREEN (Ctrl+E)")

    fails = 0

    if not _mt5_running():
        print("\n[FAIL] MT5 terminal64.exe is NOT running")
        print("  -> Open MetaTrader 5 and login first, then re-run this script")
        return 1
    print("\n[PASS] MT5 terminal is running")

    if _bot_running():
        print("[INFO] tradingbot --loop already running — skipping daemon start")
    else:
        manual = ROOT / "data" / "manual_stop.flag"
        if manual.is_file():
            print(f"[WARN] Removing stale manual_stop.flag")
            manual.unlink(missing_ok=True)

    rc = _run("MT5 autotrading", [sys.executable, "scripts/diagnose_autotrading.py", "--attach-only"])
    if rc != 0:
        fails += 1
        print("  -> Fix: Tools > Options > Expert Advisors > Allow algo trading ON")
        print("  -> Or run start\\FIX_MT5_PYTHON_API.bat once")

    rc = _run("VOL_REGIME preflight", [sys.executable, "scripts/check_vol_regime_live_setup.py"])
    if rc != 0:
        fails += 1

    rc = _run("Phase 2", [sys.executable, "scripts/verify_phase2_live_ready.py"])
    if rc != 0:
        fails += 1

    if fails:
        print(f"\n=== NOT READY — {fails} check(s) failed ===")
        print("Fix issues above before starting the bot.")
        return 1

    if _bot_running():
        print("\n=== READY — bot already LIVE ===")
        return 0

    print("\n--- Starting live daemon ---")
    ps1 = ROOT / "scripts" / "start_live_daemon.ps1"
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        print("[FAIL] start_live_daemon.ps1")
        return 1

    time.sleep(8)
    if not _bot_running():
        print("[FAIL] Bot did not start — check logs/watchdog_stderr_*.log")
        return 1

    print("\n=== SUCCESS — Bot LIVE ===")
    print("  Keep MT5 open all session")
    print("  Dashboard: RUN_DASHBOARD.bat")
    print("  Stop: start\\5_stop_bot.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
