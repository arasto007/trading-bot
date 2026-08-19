"""Find first VBScript chunk that breaks mshta execution."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"
TRACE = ROOT / "data" / "hta_bisect_ok.txt"
TEST_HTA = ROOT / "scripts" / "hta_bisect_test.hta"


def vb_block() -> list[str]:
    text = HTA.read_text(encoding="utf-8")
    marker = '<script language="VBScript">'
    start = text.index(marker) + len(marker)
    end = text.index("</script>", start)
    return text[start:end].splitlines()


def run_chunk(lines: list[str]) -> bool:
    if TRACE.exists():
        TRACE.unlink()
    body = "\n".join(lines)
    body += """
On Error Resume Next
Dim fsoT, tsT
Set fsoT = CreateObject("Scripting.FileSystemObject")
Set tsT = fsoT.CreateTextFile(""" + f'"{TRACE}"' + """, True, False)
tsT.Write "OK"
tsT.Close
"""
    TEST_HTA.write_text(
        "<!DOCTYPE html><html><head><HTA:APPLICATION /></head><body>"
        f'<script language="VBScript">\n{body}\n</script></body></html>',
        encoding="utf-8",
    )
    subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
    subprocess.Popen(
        ["mshta.exe", str(TEST_HTA)],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    for _ in range(20):
        time.sleep(0.5)
        if TRACE.exists():
            subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
            return True
    subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
    return False


def main() -> int:
    lines = vb_block()
    lo, hi = 0, len(lines)
    print("total_lines", len(lines))
    while lo < hi:
        mid = (lo + hi) // 2
        chunk = lines[: mid + 1]
        ok = run_chunk(chunk)
        print(f"lines 0..{mid} ({len(chunk)} lines):", "OK" if ok else "FAIL")
        if ok:
            lo = mid + 1
        else:
            hi = mid
    if lo < len(lines):
        print("FIRST_BAD_LINE", lo + 1, repr(lines[lo][:120]))
    else:
        print("ALL_LINES_OK_ALONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
