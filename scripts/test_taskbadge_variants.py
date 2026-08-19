#!/usr/bin/env python3
from pathlib import Path
import subprocess, time

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "live_dashboard.hta").read_text(encoding="utf-8")
m = '<script language="VBScript">'
s = text.index(m) + len(m)
e = text.index("</script>", s)
lines = text[s:e].splitlines()
OUT = ROOT / "scripts" / "hta_wrap_add.hta"
TRACE = ROOT / "data" / "hta_wrap320_ok.txt"

def run(label, extra):
    chunk = "\n".join(lines[:309] + extra)
    OUT.write_text(
        "<!DOCTYPE html><html><head><HTA:APPLICATION /></head><body>"
        f'<script language="VBScript">\n{chunk}\n'
        'Dim fso, ts: Set fso = CreateObject("Scripting.FileSystemObject")\n'
        'Set ts = fso.CreateTextFile("data\\hta_wrap320_ok.txt", True, False): ts.Write TaskBadgeHtml("ON"): ts.Close\n'
        "</script></body></html>",
        encoding="utf-8",
    )
    if TRACE.exists():
        TRACE.unlink()
    subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
    subprocess.Popen(["mshta.exe", str(OUT)], cwd=str(ROOT))
    ok = False
    for _ in range(16):
        time.sleep(0.5)
        if TRACE.exists():
            ok = True
            break
    subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
    print(label, "OK" if ok else "FAIL")

full = lines[310:317]
run("full task fn", full)
run("line313 only", full[:3])
run("with elseif", full[:5])
