#!/usr/bin/env python3
"""
End-to-end dashboard smoke test.
Run after every HTA change: python scripts/dashboard_smoke_test.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"
VBS = ROOT / "scripts" / "hta_shell.vbs"

BATS = {
    "btnGoLive": "start/START_BOT.bat",
    "btnStop": "start/5_stop_bot.bat",
    "btnPrepare": "start/GO_LIVE_FULL.bat",
    "btnCheck": "start/1_check_setup.bat",
    "btnStatus": "start/6_status.bat",
    "btnDailyReport": "start/16_daily_report.bat",
    "btnRefresh": None,
}

FAILURES: list[str] = []


def ok(msg: str) -> None:
    print("OK", msg)


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print("FAIL", msg)


def check_hta_structure() -> None:
    if not HTA.is_file():
        fail("live_dashboard.hta missing")
        return
    text = HTA.read_text(encoding="utf-8")
    status_pos = text.find('id="status"')
    script_pos = text.find('<script language="VBScript">')
    body_end = text.rfind("</body>")
    if status_pos < 0:
        fail("status element missing")
    elif script_pos < status_pos:
        fail("VBScript must come AFTER status element (DOM order)")
    else:
        ok("HTA script after DOM")
    if "BootDashboard" in text[script_pos:script_pos + 500]:
        fail("BootDashboard must not run at parse time")
    else:
        ok("no parse-time boot")
    if "RunSnapshotSync" in text and "False" not in text.split("RunSnapshot")[1][:200]:
        pass
    if "sh.Run cmd, 0, False" in text or "sh.Run cmd, 0, False" in VBS.read_text(encoding="utf-8"):
        ok("snapshot runs async")
    else:
        fail("snapshot should be async (sh.Run wait=False)")
    missing_btns = [btn for btn in BATS if f'id="{btn}"' not in text]
    if missing_btns:
        fail(f"button ids missing: {missing_btns}")
    else:
        ok("all button ids present")
    for btn in BATS:
        if btn != "btnRefresh" and f"Sub {btn}_OnClick" not in VBS.read_text(encoding="utf-8"):
            fail(f"VBS handler missing: {btn}_OnClick")
    ok("VBS click handlers")
    if "Sub btnRefresh_OnClick()" in VBS.read_text(encoding="utf-8"):
        fail("VBS subs must not use empty parentheses")
    else:
        ok("VBS sub syntax")
    if "v9.1.0" not in text:
        fail("version v9.1.0 not in HTA")
    else:
        ok("version v9.1.0")


def check_bats_exist() -> None:
    for btn, rel in BATS.items():
        if rel and not (ROOT / rel.replace("/", "\\")).is_file():
            fail(f"missing bat for {btn}: {rel}")
    ok("launcher bats exist")


def check_snapshot_pipeline() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "status_snapshot.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        fail(f"status_snapshot.py exit {proc.returncode}: {proc.stderr[:300]}")
        return
    out = proc.stdout
    for key in ("STATE|", "UTC|", "ACCOUNT|"):
        if key not in out:
            fail(f"snapshot missing {key}")
    cache = ROOT / "data" / "hta_dashboard_snapshot.txt"
    html = ROOT / "data" / "dashboard_live.html"
    if not cache.is_file() or cache.stat().st_size < 100:
        fail("hta_dashboard_snapshot.txt missing or tiny")
    elif not html.is_file() or html.stat().st_size < 500:
        fail("dashboard_live.html missing or tiny")
    else:
        ok(f"snapshot pipeline ({cache.stat().st_size}b cache, {html.stat().st_size}b html)")
    m = re.search(r"UTC\|([^\n]+)", out)
    if m and m.group(1) in html.read_text(encoding="utf-8"):
        ok("UTC propagated to html")
    else:
        fail("UTC not found in dashboard_live.html")


def check_project_root_vbs() -> None:
    proc = subprocess.run(
        ["cscript", "//nologo", str(ROOT / "scripts" / "test_hta_project_root.vbs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    line = proc.stdout.strip()
    if not line.startswith("OK|"):
        fail(f"test_hta_project_root.vbs: {line} {proc.stderr}")
    elif "TradingBot" not in line:
        fail(f"bad root path: {line}")
    else:
        ok(f"project root: {line.split('|', 1)[1]}")


def main() -> int:
    print("=== Dashboard smoke test ===")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_hta_shell.py")], check=True, cwd=ROOT)
    check_hta_structure()
    check_bats_exist()
    check_project_root_vbs()
    check_snapshot_pipeline()
    print("=== Summary ===")
    if FAILURES:
        for f in FAILURES:
            print(" -", f)
        print(f"FAILED ({len(FAILURES)} issues)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
