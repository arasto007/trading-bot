#!/usr/bin/env python3
"""Local web dashboard for TradingBot control and status."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PORT = 18765
VERSION = "v10.0.0"
PID_FILE = ROOT / "data" / "dashboard_server.pid"

ACTIONS: dict[str, dict[str, object]] = {
    "start": {"bat": "start/START_BOT.bat", "sync": False, "refresh_after": 8},
    "stop": {"bat": "start/5_stop_bot.bat", "sync": True, "args": ["--nopause"], "refresh_after": 2},
    "repair": {"bat": "start/GO_LIVE_FULL.bat", "sync": False, "refresh_after": 8},
    "check": {"bat": "start/1_check_setup.bat", "sync": False},
    "status": {"bat": "start/6_status.bat", "sync": False, "refresh_after": 5},
    "report": {"bat": "start/16_daily_report.bat", "sync": False},
}

SHELL_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>TradingBot Sovereign {version}</title>
<style>
html,body{{margin:0;height:100%;overflow:hidden;background:#0E0E10;color:#E8E6E3;font-family:Segoe UI,Tahoma,Arial}}
.bar{{height:54px;background:#141418;border-bottom:1px solid #2A2A30;display:flex;align-items:center;padding:0 12px;gap:8px}}
.brand{{font-weight:700;color:#D4AF37;font-size:15px;min-width:180px}}
.sub{{font-size:10px;color:#5C5854}}
.btns{{flex:1;text-align:center}}
.btn{{margin:0 3px;padding:6px 12px;border:1px solid #2A2A30;background:#1A1A20;color:#E8E6E3;font-size:11px;cursor:pointer;border-radius:4px}}
.btn-go{{border-color:#3DDC84;color:#3DDC84;background:#0F1A14}}
.btn-stop{{border-color:#FF6B6B;color:#FF6B6B;background:#1A1010}}
.btn-acc{{border-color:#6B5A2E;color:#D4AF37;background:#1A1610}}
#status{{color:#7CB8FF;font:11px Consolas,monospace;min-width:320px;text-align:right}}
#panel{{width:100%;height:calc(100% - 54px);border:0;background:#0E0E10}}
</style></head>
<body>
<div class="bar">
  <div><div class="brand">SOVEREIGN</div><div class="sub">XAUUSD M5 | {version}</div></div>
  <div class="btns">
    <button class="btn btn-go" onclick="act('start')">START</button>
    <button class="btn btn-stop" onclick="act('stop')">STOP</button>
    <button class="btn btn-acc" onclick="act('repair')">Repair MT5</button>
    <button class="btn" onclick="act('check')">Check</button>
    <button class="btn" onclick="act('status')">Status</button>
    <button class="btn" onclick="act('report')">Report</button>
    <button class="btn btn-acc" onclick="refreshPanel()">Refresh</button>
  </div>
  <div id="status">Loading...</div>
</div>
<iframe id="panel" src="/panel"></iframe>
<script>
async function act(name) {{
  setStatus('Running ' + name + '...');
  try {{
    const r = await fetch('/api/action/' + name, {{method:'POST'}});
    const j = await r.json();
    setStatus(j.message || 'done');
    if (j.refresh_after) setTimeout(refreshPanel, j.refresh_after * 1000);
  }} catch (e) {{
    setStatus('Error: ' + e);
  }}
}}
async function refreshPanel() {{
  setStatus('Refreshing...');
  try {{
    const r = await fetch('/api/refresh', {{method:'POST'}});
    const j = await r.json();
    document.getElementById('panel').src = '/panel?t=' + Date.now();
    setStatus(j.message || 'OK');
  }} catch (e) {{
    setStatus('Refresh error: ' + e);
  }}
}}
function setStatus(msg) {{ document.getElementById('status').textContent = msg; }}
refreshPanel();
setInterval(refreshPanel, 30000);
</script>
</body></html>
"""


def _python_exe() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.is_file() else sys.executable


def run_snapshot() -> tuple[bool, str]:
    py = _python_exe()
    proc = subprocess.run(
        [py, str(ROOT / "scripts" / "status_snapshot.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    html = ROOT / "data" / "dashboard_live.html"
    if proc.returncode != 0 or not html.is_file():
        err = (proc.stderr or proc.stdout or "snapshot failed")[:200]
        return False, err
    utc = "-"
    for line in proc.stdout.splitlines():
        if line.startswith("UTC|"):
            utc = line[4:]
            break
    return True, f"OK {html.stat().st_size}b | UTC {utc} | 30s"


def run_bat(rel: str, *, sync: bool = False, extra: list[str] | None = None) -> tuple[int, str]:
    bat = ROOT / rel.replace("/", os.sep)
    if not bat.is_file():
        return 1, f"Missing {rel}"
    cmd = ["cmd", "/c", "call", str(bat)] + (extra or [])
    if sync:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
        if proc.returncode == 0:
            return 0, f"Done {rel}"
        return proc.returncode, f"Failed {rel}: {(proc.stderr or proc.stdout)[:120]}"
    subprocess.Popen(
        cmd,
        cwd=ROOT,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    return 0, f"Launched {rel}"


def kill_old_server() -> None:
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._text(200, SHELL_HTML.format(version=VERSION))
            return
        if path == "/panel":
            html = ROOT / "data" / "dashboard_live.html"
            if not html.is_file():
                run_snapshot()
            if html.is_file():
                self._text(200, html.read_text(encoding="utf-8", errors="replace"))
            else:
                self._text(503, "<html><body>Panel not ready. Click Refresh.</body></html>")
            return
        if path == "/api/health":
            self._json(200, {"ok": True, "version": VERSION})
            return
        self._text(404, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/refresh":
            ok, msg = run_snapshot()
            self._json(200 if ok else 500, {"ok": ok, "message": msg})
            return
        if path.startswith("/api/action/"):
            name = path.rsplit("/", 1)[-1]
            spec = ACTIONS.get(name)
            if not spec:
                self._json(404, {"ok": False, "message": f"Unknown action {name}"})
                return
            code, msg = run_bat(
                str(spec["bat"]),
                sync=bool(spec.get("sync")),
                extra=list(spec["args"]) if spec.get("args") else None,
            )
            payload: dict[str, object] = {"ok": code == 0, "message": msg}
            if spec.get("refresh_after"):
                payload["refresh_after"] = spec["refresh_after"]
            self._json(200 if code == 0 else 500, payload)
            return
        self._json(404, {"ok": False, "message": "Not found"})


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    kill_old_server()
    ok, msg = run_snapshot()
    if not ok:
        print("WARN snapshot:", msg, file=sys.stderr)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Dashboard {VERSION} -> {url}")
    print(msg)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if PID_FILE.is_file():
            PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
