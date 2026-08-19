#!/usr/bin/env python3
"""Install panel-loader VBScript into live_dashboard.hta (head, single block)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"
VBS_FILE = ROOT / "scripts" / "hta_dashboard.vbs"

VERSION = "v8.7.2-FIX"


def main() -> int:
    vbs = VBS_FILE.read_text(encoding="utf-8").strip()
    if "Call InitDashboard" not in vbs:
        vbs = vbs + "\n\nCall InitDashboard"
    text = HTA.read_text(encoding="utf-8")
    text = re.sub(
        r'<script\s+language="VBScript">[\s\S]*?</script>\s*',
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r'\s*onLoad="InitDashboard"\s*language="VBScript"\s*',
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r'\s*language="VBScript"\s*onLoad="InitDashboard"\s*',
        " ",
        text,
        flags=re.I,
    )
    script = f'\n<script language="VBScript">\n{vbs}\n</script>\n'
    text = text.replace("</body>", script + "</body>", 1)
    text = re.sub(r"v8\.[0-9.]+-[A-Z]+", VERSION, text)
    HTA.write_text(text, encoding="utf-8")
    print("OK", VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
