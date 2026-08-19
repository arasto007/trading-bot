#!/usr/bin/env python3
"""وضعیت ربات live."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "data" / "trade_journal.db"
LOG = ROOT / "logs" / "watchdog_stderr.log"


def main() -> int:
    print("=== TradingBot Live Status ===")
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'watchdog|tradingbot.*--loop' } | "
                "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out and out != "":
            print("[RUNNING]")
            print(out)
        else:
            print("[STOPPED]")
            print("  Start hidden: powershell -File scripts\\start_live_daemon.ps1")
            print("  Start visible: powershell -File scripts\\start_live_visible.ps1")
    except Exception:
        print("[UNKNOWN] could not query processes")

    if LOG.exists():
        print("\n--- last log lines ---")
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-6:]:
            print(f"  {line}")

    if JOURNAL.exists():
        conn = sqlite3.connect(JOURNAL)
        cur = conn.cursor()
        cur.execute(
            "SELECT ts, market, state, detail FROM cycle_events ORDER BY id DESC LIMIT 4"
        )
        print("\n--- last cycles ---")
        for r in cur.fetchall():
            print(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]}")
        print(f"now utc: {datetime.now(timezone.utc).strftime('%H:%M:%S')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
