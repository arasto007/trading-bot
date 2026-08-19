#!/usr/bin/env python3
"""Weekend readiness checklist — pre-LIVE verification (Telegram optional)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

# (label, script relative to ROOT, max acceptable exit code)
CHECKS: list[tuple[str, str, int]] = [
    ("VOL setup (MT5 + config)", "scripts/check_vol_regime_live_setup.py", 1),
    ("VOL stack ready", "scripts/verify_vol_regime_live_ready.py", 0),
    ("Phase 2 (demo + ops)", "scripts/verify_phase2_live_ready.py", 0),
    ("Phase 4 (prop + drift)", "scripts/verify_phase4_live_ready.py", 0),
    ("Status snapshot", "scripts/status_snapshot.py", 0),
]


def _run_script(rel: str) -> tuple[int, str]:
    path = ROOT / rel.replace("/", os.sep)
    if not path.is_file():
        return 127, f"MISSING: {path}"
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _telegram_status() -> str:
    tg = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    return "configured" if tg else "optional (off)"


def main() -> int:
    print("=" * 60)
    print("  WEEKEND READINESS CHECKLIST")
    print("  Telegram:", _telegram_status())
    print("=" * 60)
    print()

    results: list[tuple[str, bool, str]] = []
    for label, script, max_rc in CHECKS:
        print(f"--- {label} ---")
        rc, output = _run_script(script)
        if output:
            print(output)
        ok = rc <= max_rc
        if rc == 127:
            ok = False
        status = "PASS" if ok else "FAIL"
        note = f"exit={rc}" if rc != 0 else "ok"
        if not ok and max_rc == 1 and rc == 1:
            note = "exit=1 (MT5 offline — open terminal before Monday LIVE)"
        results.append((label, ok, note))
        print(f"[{status}] {label} ({note})")
        print()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("=" * 60)
    print(f"  SUMMARY: {passed}/{total} PASS")
    for label, ok, note in results:
        mark = "PASS" if ok else "FAIL"
        print(f"    [{mark}] {label} — {note}")
    print("=" * 60)

    if passed == total:
        print("\nWEEKEND CHECK: READY for Monday LIVE (demo account, no Telegram required)")
        return 0
    print("\nWEEKEND CHECK: NOT READY — fix FAIL items before Monday LIVE")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
