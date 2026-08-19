#!/usr/bin/env python3
"""Move VBScript to HEAD, remove broken onclick handlers."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"


def main() -> int:
    text = HTA.read_text(encoding="utf-8")
    m = re.search(r"<script\s+language\s*=\s*[\"']VBScript[\"']\s*>", text, re.I)
    if not m:
        raise SystemExit("VBScript block not found")
    start = m.start()
    end = text.lower().find("</script>", start)
    if end < 0:
        raise SystemExit("closing script tag not found")
    end += len("</script>")
    script_block = text[start:end]
    script_block = re.sub(
        r"\nwindow\.setTimeout\s+\"InitDashboard\",\s*500\s*\n",
        "\n",
        script_block,
        flags=re.I,
    )

    head_part = text[:start]
    tail = text[end:]
    tail = tail.replace(script_block, "")
    tail = re.sub(r'\s+onclick="[^"]*"', "", tail)
    tail = re.sub(r"\s+onclick='[^']*'", "", tail)
    tail = tail.replace(' onload="VBScript:InitDashboard"', "")

    head_end = head_part.rindex("</head>")
    new_head = head_part[:head_end] + script_block + "\n" + head_part[head_end:]
    new_head = new_head.replace("v8.4.6-LOAD", "v8.5.0-HTA")
    out = new_head + tail
    if not out.endswith("\n"):
        out += "\n"

    HTA.write_text(out, encoding="utf-8")
    script_pos = out.lower().find("<script")
    body_pos = out.lower().find("<body")
    onclick_n = len(re.findall(r"onclick\s*=", out, re.I))
    print(f"OK script_before_body={script_pos < body_pos} onclick={onclick_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
