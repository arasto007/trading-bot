#!/usr/bin/env python3
"""Clean remaining literal < in HTA VBScript after partial Chr migration."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"


def main() -> int:
    text = HTA.read_text(encoding="utf-8")
    marker = '<script language="VBScript">'
    start = text.index(marker)
    end = text.index("</script>", start)
    head = text[: start + len(marker)]
    block = text[start + len(marker) : end]
    tail = text[end:]

    block = block.replace("\nBootTrace \"script_parsed\"\n", "\n")
    block = re.sub(
        r'Function Lt\(\)[\s\S]*?End Function\s*Function Gt\(\)[\s\S]*?End Function\s*',
        "",
        block,
        count=1,
    )

    reps = [
        ('"" & Chr(60) & "<" & "/span>" & ""', "Chr(60) & \"/span\" & Chr(62)"),
        ('"" & Chr(60) & "<" & "/div>" & ""', "Chr(60) & \"/div\" & Chr(62)"),
        ('"" & Chr(60) & "<" & "/td>" & ""', "Chr(60) & \"/td\" & Chr(62)"),
        ('"" & Chr(60) & "<" & "/tr>" & ""', "Chr(60) & \"/tr\" & Chr(62)"),
        ('"" & Chr(60) & "<" & "/table>" & ""', "Chr(60) & \"/table\" & Chr(62)"),
        ('" & "<" & "', "Chr(60) & \""),
        ('"<', "Chr(60) & \""),
    ]
    for old, new in reps:
        block = block.replace(old, new)

    # status & "" & Chr(60) -> status & Chr(60)
    block = block.replace(' & "" & Chr(60)', " & Chr(60)")

    text = head + block + tail
    text = text.replace("v8.6.3-CHR", "v8.6.4-CHR").replace("v8.6.2-FIX", "v8.6.4-CHR")
    HTA.write_text(text, encoding="utf-8")
    print("OK remaining_lt", block.count("<"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
