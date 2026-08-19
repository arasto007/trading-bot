#!/usr/bin/env python3
"""Rebuild HTA: one main VBScript block at body end + FOR/EVENT button wiring."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"

FOR_EVENTS = """
<script language="VBScript" for="btnGoLive" event="onclick">
RunBatFile "start\\START_BOT.bat"
</script>
<script language="VBScript" for="btnStop" event="onclick">
RunStopBot
</script>
<script language="VBScript" for="btnPrepare" event="onclick">
RunBatFile "start\\GO_LIVE_FULL.bat"
</script>
<script language="VBScript" for="btnCheck" event="onclick">
RunBatFile "start\\1_check_setup.bat"
</script>
<script language="VBScript" for="btnStatus" event="onclick">
RunBatFile "start\\6_status.bat"
</script>
<script language="VBScript" for="btnBacktest" event="onclick">
ToggleBacktestPanel
</script>
<script language="VBScript" for="btnDailyReport" event="onclick">
RunBatFile "start\\16_daily_report.bat"
</script>
<script language="VBScript" for="btnRefresh" event="onclick">
RefreshLivePanel
</script>
<script language="VBScript" for="btnRunBacktest" event="onclick">
RunCustomBacktest
</script>
<script language="VBScript" for="btnCloseBacktest" event="onclick">
ToggleBacktestPanel
</script>
"""


def extract_vbscript(text: str) -> str:
    chunks: list[str] = []
    for m in re.finditer(
        r"<script\s+language\s*=\s*[\"']VBScript[\"']\s*>(.*?)</script>",
        text,
        re.I | re.S,
    ):
        body = m.group(1).strip()
        if body and body != "InitDashboard":
            chunks.append(body)
    if not chunks:
        raise SystemExit("no VBScript body found")
    merged = "\n\n".join(chunks)
    # dedupe duplicate Sub blocks from prior merges
    seen: set[str] = set()
    out_lines: list[str] = []
    for line in merged.splitlines():
        if line.startswith("Sub ") or line.startswith("Function "):
            key = line.split("(")[0].strip()
            if key in seen:
                continue
            seen.add(key)
        out_lines.append(line)
    return "\n".join(out_lines)


def main() -> int:
    text = HTA.read_text(encoding="utf-8")
    vb = extract_vbscript(text)
    vb = vb.replace("v8.5.1-BOOT", "v8.6.0-ONE")
    vb = re.sub(r"\nSub btn\w+_OnClick[\s\S]*?End Sub\n", "\n", vb)

    head_end = text.index("</head>")
    head = text[:head_end]
    head = re.sub(
        r"<script\s+language\s*=\s*[\"']VBScript[\"'][\s\S]*?</script>\s*",
        "",
        head,
        flags=re.I,
    )
    head = head.rstrip() + "\n</head>\n"

    body_start = text.index("<body")
    body = text[body_start:]
    body = re.sub(
        r"<script\s+language\s*=\s*[\"']VBScript[\"'][\s\S]*?</script>\s*",
        "",
        body,
        flags=re.I,
    )
    body = body.replace("v8.5.1-BOOT", "v8.6.0-ONE")
    body = body.replace("</body>", "").replace("</html>", "").rstrip()

    main_script = (
        '<script language="VBScript">\n'
        + vb
        + "\n\nCall InitDashboard\n</script>\n"
        + FOR_EVENTS
        + "\n</body>\n</html>\n"
    )
    out = head + body + "\n\n" + main_script
    HTA.write_text(out, encoding="utf-8")
    print("OK", "v8.6.0-ONE", "vb_lines", vb.count("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
