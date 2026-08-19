#!/usr/bin/env python3
"""Escape </tag> sequences inside HTA VBScript strings (MSHTML truncates script)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"

CLOSE_TAG = re.compile(r"</([a-zA-Z][a-zA-Z0-9]*)>")


def patch_vbscript_block(text: str) -> tuple[str, int]:
    marker = '<script language="VBScript">'
    start = text.index(marker)
    end = text.index("</script>", start)
    head = text[: start + len(marker)]
    block = text[start + len(marker) : end]
    tail = text[end:]

    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        tag = m.group(1)
        n += 1
        return '" & "<" & "/' + tag + '>" & "'

    block = CLOSE_TAG.sub(repl, block)
    return head + block + tail, n


def main() -> int:
    text = HTA.read_text(encoding="utf-8")
    patched, count = patch_vbscript_block(text)
    if count == 0:
        print("no changes")
        return 0
    text = patched.replace("v8.6.1-ONE", "v8.6.2-FIX")
    HTA.write_text(text, encoding="utf-8")
    print("OK patched_close_tags", count, "v8.6.2-FIX")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
