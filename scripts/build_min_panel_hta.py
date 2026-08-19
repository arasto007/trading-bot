#!/usr/bin/env python3
"""Build minimal-body HTA keeping same VBScript block."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
hta = ROOT / "live_dashboard.hta"
text = hta.read_text(encoding="utf-8")
s = text.index('<script language="VBScript">')
e = text.index("</script>", s) + len("</script>")
vb = text[s:e]
ids = [
    "action-status", "live-state", "live-utc", "hero-equity", "hero-pnl",
    "sys-status", "api-status", "demo-banner", "footer-api", "footer-watchdog",
    "footer-bot", "footer-latency", "card-proc", "kpi-pf", "kpi-expr", "kpi-accept",
    "kpi-pf-sub", "card-ml", "card-ml-detail", "engine-list", "task-list",
    "signal-stream", "live-cycles", "live-log", "live-phase4", "alert-banner",
    "bt-start-date", "bt-end-date", "bt-start-time", "bt-end-time", "bt-balance",
    "bt-symbol", "backtest-panel", "btnRefresh",
]
divs = "\n".join(f'<div id="{i}"></div>' for i in ids)
out = ROOT / "scripts" / "hta_min_panel.hta"
out.write_text(
    "<!DOCTYPE html><html><head><HTA:APPLICATION /></head><body>"
    + divs
    + '<input type="button" id="btnRefresh" value="Refresh" />'
    + vb
    + "</body></html>",
    encoding="utf-8",
)
print("wrote", out)
