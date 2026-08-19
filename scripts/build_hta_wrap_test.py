"""Build minimal HTA wrapping live_dashboard VBScript for smoke test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
hta = ROOT / "live_dashboard.hta"
text = hta.read_text(encoding="utf-8")
marker = '<script language="VBScript">'
start = text.index(marker)
end = text.index("</script>", start)
vb = text[start : end + len("</script>")]
shell = """<!DOCTYPE html>
<html><head>
<HTA:APPLICATION SHOWINTASKBAR="yes" SINGLEINSTANCE="no" />
<title>HTA VB wrap test</title>
</head><body>
<div id="action-status"></div>
<div id="live-state"></div>
<div id="live-utc"></div>
<div id="hero-equity"></div>
<div id="hero-pnl"></div>
<div id="sys-status"></div>
<div id="api-status"></div>
<div id="demo-banner"></div>
<div id="footer-api"></div>
<div id="footer-watchdog"></div>
<div id="footer-bot"></div>
<div id="footer-latency"></div>
<div id="card-proc"></div>
<div id="kpi-pf"></div>
<div id="kpi-expr"></div>
<div id="kpi-accept"></div>
<div id="kpi-pf-sub"></div>
<div id="card-ml"></div>
<div id="card-ml-detail"></div>
<div id="engine-list"></div>
<div id="task-list"></div>
<div id="signal-stream"></div>
<div id="live-cycles"></div>
<div id="live-log"></div>
<div id="live-phase4"></div>
<div id="alert-banner"></div>
<div id="dot-pa"></div>
<div id="dot-vol"></div>
<div id="dot-adp"></div>
<div id="dot-ml"></div>
<div id="bt-start-date"></div>
<div id="bt-end-date"></div>
<div id="bt-start-time"></div>
<div id="bt-end-time"></div>
<div id="bt-balance"></div>
<div id="bt-symbol"></div>
<div id="backtest-panel" style="display:none"></div>
"""
out = ROOT / "scripts" / "hta_wrap_test.hta"
out.write_text(shell + vb + "\n</body></html>\n", encoding="utf-8")
print("wrote", out, "bytes", out.stat().st_size)
