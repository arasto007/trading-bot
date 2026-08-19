import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "live_dashboard.hta").read_text(encoding="utf-8")
s = text.index('<script language="VBScript">')
e = text.index("</script>", s) + len("</script>")
vb = text[s:e]
OUT = ROOT / "scripts" / "hta_vb_only.hta"
MARK = ROOT / "data" / "hta_head_ran.txt"
OUT.write_text(
    "<!DOCTYPE html><html><head><HTA:APPLICATION /></head><body>"
    '<div id="action-status"></div>'
    + vb
    + '<script language="VBScript">BootNow</script></body></html>',
    encoding="utf-8",
)
if MARK.exists():
    MARK.unlink()
subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
subprocess.Popen(["mshta.exe", str(OUT)], cwd=str(ROOT))
for _ in range(16):
    time.sleep(0.5)
    if MARK.exists():
        print("VB_ONLY_OK", MARK.read_text())
        break
else:
    print("VB_ONLY_FAIL")
subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
