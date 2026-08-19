#!/usr/bin/env python3
"""One-click start live bot — MT5 must be open. No restart, no 5-step maze."""

from __future__ import annotations

import json
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


def _bot_pid() -> int | None:
    try:
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
            timeout=12,
        ).strip()
        if not out:
            return None
        pid = json.loads(out).get("ProcessId")
        return int(pid) if pid else None
    except Exception:
        return None


def _watchdog_pid() -> int | None:
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'run_live_watchdog' } | "
                "Select-Object -First 1 ProcessId | ConvertTo-Json -Compress",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=12,
        ).strip()
        if not out:
            return None
        pid = json.loads(out).get("ProcessId")
        return int(pid) if pid else None
    except Exception:
        return None


def _mt5_running() -> bool:
    from tradingbot.adapters.mt5_utils import _is_terminal_process_running
    from tradingbot.adapters.legacy_loader import load_legacy_config

    return _is_terminal_process_running(load_legacy_config())


def _wait_mt5(seconds: int = 60) -> bool:
    if _mt5_running():
        return True
    print("MT5 باز نیست — 60 ثانیه صبر می‌کنم (MT5 را باز کن + Login)...")
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _mt5_running():
            print("MT5 پیدا شد.")
            time.sleep(3)
            return True
        time.sleep(5)
        print("  ...")
    return False


def main() -> int:
    print("=" * 48)
    print("  START BOT — VOL_REGIME LIVE")
    print("=" * 48)

    pid = _bot_pid()
    if pid:
        print(f"\nربات از قبل RUNNING است (PID {pid})")
        print("Dashboard را refresh کن — کاری لازم نیست.")
        return 0

    if not _wait_mt5(60):
        print("\n[FAIL] MetaTrader 5 باز نیست.")
        print("  1) MT5 را باز کن و Login کن")
        print("  2) Ctrl+E سبز (Algo Trading)")
        print("  3) دوباره START_BOT.bat را بزن")
        return 1

    manual = ROOT / "data" / "manual_stop.flag"
    if manual.is_file():
        manual.unlink(missing_ok=True)
        print("manual_stop پاک شد.")

    print("\nدر حال start ربات...")
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "start_live_daemon.ps1"),
        ],
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        print("\n[FAIL] start_live_daemon — logs\\watchdog_stderr_*.log را ببین")
        return 1

    print("منتظر بالا آمدن tradingbot...")
    for _ in range(24):
        time.sleep(5)
        pid = _bot_pid()
        if pid:
            wd = _watchdog_pid()
            print(f"\n=== OK — ربات LIVE شد ===")
            print(f"  Bot PID:      {pid}")
            if wd:
                print(f"  Watchdog PID: {wd}")
            print("  MT5 را باز نگه دار (Algo Trading سبز)")
            print("  توقف: start\\5_stop_bot.bat")
            return 0

    print("\n[FAIL] watchdog بالا آمد ولی tradingbot start نشد.")
    print("  احتمالاً MT5 attach نشد — MT5 را Login کن و دوباره بزن")
    latest = ROOT / "logs" / "watchdog_latest.logpaths.txt"
    if latest.is_file():
        print(f"  Log: {latest.read_text(encoding='utf-8').strip()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
