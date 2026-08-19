import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"
text = HTA.read_text(encoding="utf-8")
s = text.index('<script language="VBScript">')
e = text.index("</script>", s) + len("</script>")
vb = text[s:e]
style_start = text.index("<style>")
style_end = text.index("</style>") + len("</style>")
style = text[style_start:style_end]
hta_app = text[text.index("<HTA:APPLICATION") : text.index("/>") + 2]
TRACE = ROOT / "data" / "hta_inc_ok.txt"
OUT = ROOT / "scripts" / "hta_incremental.hta"

def run(label: str, body: str) -> bool:
    OUT.write_text(
        "<!DOCTYPE html><html><head>"
        + hta_app
        + style
        + vb
        + "</head><body>"
        + body
        + "</body></html>",
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
    return ok

run("minimal", '<div id="action-status"></div>')
body = text[text.index("<body") : text.index("</body>")]
run("full_body", body)
