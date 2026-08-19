#!/usr/bin/env python3
"""Build HTA shell: toolbar VBScript after DOM, iframe for live panel."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"
VBS = ROOT / "scripts" / "hta_shell.vbs"
VERSION = "v9.1.0"

HTA_TEMPLATE = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=11">
<HTA:APPLICATION
  APPLICATIONNAME="TradingBot Sovereign"
  BORDER="thin"
  CAPTION="yes"
  MAXIMIZEBUTTON="yes"
  MINIMIZEBUTTON="yes"
  SHOWINTASKBAR="yes"
  SINGLEINSTANCE="yes"
  SYSMENU="yes"
  SCROLL="no"
  WINDOWSTATE="maximize"
/>
<title>TradingBot Sovereign {version}</title>
<style>
html, body {{ width:100%; height:100%; margin:0; padding:0; overflow:hidden; background:#0E0E10; }}
.bar {{ height:54px; background:#141418; border-bottom:1px solid #2A2A30; }}
.bar-inner {{ width:100%; height:54px; border-collapse:collapse; }}
.brand {{ font-size:15px; font-weight:700; color:#D4AF37; letter-spacing:1px; padding-left:16px; }}
.sub {{ font-size:10px; color:#5C5854; padding-left:16px; }}
.btn {{ margin:0 3px; padding:6px 12px; border:1px solid #2A2A30; background:#1A1A20; color:#E8E6E3; font-size:11px; cursor:pointer; border-radius:4px; }}
.btn-go {{ border-color:#3DDC84; color:#3DDC84; background:#0F1A14; }}
.btn-stop {{ border-color:#FF6B6B; color:#FF6B6B; background:#1A1010; }}
.btn-acc {{ border-color:#6B5A2E; color:#D4AF37; background:#1A1610; }}
#status {{ color:#7CB8FF; font-size:11px; font-family:Consolas,monospace; padding-right:16px; text-align:right; }}
#liveframe {{ width:100%; height:calc(100% - 54px); border:0; background:#0E0E10; }}
</style>
</head>
<body>
<table class="bar-inner bar" cellpadding="0" cellspacing="0">
<tr>
  <td style="width:220px">
    <div class="brand">SOVEREIGN</div>
    <div class="sub">XAUUSD M5 PA + Meta | {version}</div>
  </td>
  <td align="center">
    <input type="button" id="btnGoLive" class="btn btn-go" value="START">
    <input type="button" id="btnStop" class="btn btn-stop" value="STOP">
    <input type="button" id="btnPrepare" class="btn btn-acc" value="Repair MT5">
    <input type="button" id="btnCheck" class="btn" value="Check">
    <input type="button" id="btnStatus" class="btn" value="Status">
    <input type="button" id="btnDailyReport" class="btn" value="Report">
    <input type="button" id="btnRefresh" class="btn btn-acc" value="Refresh">
  </td>
  <td style="width:420px"><div id="status">Loading...</div></td>
</tr>
</table>
<iframe id="liveframe" src="data/dashboard_live.html"></iframe>
<script language="VBScript">
{vbs}
</script>
</body>
</html>
"""


def main() -> int:
    vbs = VBS.read_text(encoding="utf-8").strip()
    HTA.write_text(
        HTA_TEMPLATE.format(version=VERSION, vbs=vbs),
        encoding="utf-8",
    )
    print("OK", HTA, VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
