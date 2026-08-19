#!/usr/bin/env python3
from pathlib import Path
import subprocess, time

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "live_dashboard.hta").read_text(encoding="utf-8")
m = '<script language="VBScript">'
s = text.index(m) + len(m)
e = text.index("</script>", s)
lines = text[s:e].splitlines()
OUT = ROOT / "scripts" / "hta_json_fix_test.hta"
TRACE = ROOT / "data" / "hta_wrap320_ok.txt"

def run(label, chunk_lines, tail):
    OUT.write_text(
        "<!DOCTYPE html><html><head><HTA:APPLICATION /></head><body>"
        f'<script language="VBScript">\n' + "\n".join(chunk_lines) + "\n"
        f'Dim fso, ts: Set fso = CreateObject("Scripting.FileSystemObject")\n'
        f'Set ts = fso.CreateTextFile("data\\\\hta_wrap320_ok.txt", True, False): {tail}\n'
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

base = lines[:309]
fixed = base.copy()
fixed[303] = '  json = "{""start"":""x"",""end"":""y"",""balance"":1000,""symbol"":""XAUUSD""}"'
run("309+task original json", base + lines[310:317], 'ts.Write TaskBadgeHtml("ON"): ts.Close')
run("309+task fixed json", fixed + lines[310:317], 'ts.Write TaskBadgeHtml("ON"): ts.Close')
