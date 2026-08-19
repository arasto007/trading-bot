import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
vbs = (ROOT / "scripts" / "hta_dashboard.vbs").read_text(encoding="utf-8")
OUT = ROOT / "scripts" / "hta_smoke_panel.hta"
OUT.write_text(
    "<!DOCTYPE html><html><head><HTA:APPLICATION /></head>"
    '<body>'
    '<div id="action-status"></div><div id="live-state"></div>'
    '<div id="live-utc"></div><div id="hero-equity"></div><div id="hero-pnl"></div>'
    '<div id="sys-status"></div><div id="api-status"></div><div id="demo-banner"></div>'
    '<div id="footer-api"></div><div id="footer-watchdog"></div><div id="footer-bot"></div>'
    '<div id="footer-latency"></div><div id="card-proc"></div>'
    '<div id="kpi-pf"></div><div id="kpi-expr"></div><div id="kpi-accept"></div>'
    '<div id="kpi-pf-sub"></div><div id="card-ml"></div><div id="card-ml-detail"></div>'
    '<div id="engine-list"></div><div id="task-list"></div><div id="signal-stream"></div>'
    '<div id="live-cycles"></div><div id="live-log"></div><div id="live-phase4"></div>'
    '<div id="alert-banner"></div>'
    '<div id="bt-start-date"></div><div id="bt-end-date"></div>'
    '<div id="bt-start-time"></div><div id="bt-end-time"></div>'
    '<div id="bt-balance"></div><div id="bt-symbol"></div>'
    '<div id="backtest-panel" style="display:none"></div>'
    f'<script language="VBScript">\n{vbs}\n</script></body></html>',
    encoding="utf-8",
)
subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
subprocess.Popen(["mshta.exe", str(OUT)], cwd=str(ROOT))
ok = False
for _ in range(20):
    time.sleep(0.5)
    snap = ROOT / "data" / "hta_dashboard_snapshot.txt"
    if (ROOT / "data" / "hta_engine.html").exists() and snap.exists():
        ok = True
        break
subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
print("SMOKE", "OK" if ok else "FAIL")
