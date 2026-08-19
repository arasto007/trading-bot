#!/usr/bin/env python3
"""Remove literal < and > from HTA VBScript strings (MSHTML truncates script)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"

STRING_RE = re.compile(r'"([^"]*)"')


def vbs_string_expr(content: str) -> str:
    if "<" not in content and ">" not in content:
        return f'"{content}"'
    parts: list[str] = []
    i = 0
    while i < len(content):
        if content[i] == "<":
            j = content.find(">", i)
            if j == -1:
                parts.append(f'Chr(60) & "{content[i:]}"')
                break
            tag = content[i + 1 : j]
            parts.append(f'Chr(60) & "{tag}" & Chr(62)')
            i = j + 1
        else:
            j = i
            while j < len(content) and content[j] != "<":
                j += 1
            chunk = content[i:j]
            if chunk:
                parts.append(f'"{chunk}"')
            i = j
    return " & ".join(p for p in parts if p)


def transform_line(line: str) -> str:
    if "<" not in line:
        return line

    def repl(m: re.Match[str]) -> str:
        return vbs_string_expr(m.group(1))

    return STRING_RE.sub(repl, line)


def patch_block(block: str) -> str:
    lines = block.splitlines()
    helper = [
        "Function Lt()",
        "  Lt = Chr(60)",
        "End Function",
        "",
        "Function Gt()",
        "  Gt = Chr(62)",
        "End Function",
        "",
    ]
    out: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and line.startswith("Function LinePrefix"):
            out.extend(helper)
            inserted = True
        if "<" in line and ('"' in line or "& Chr(60)" in line):
            line = transform_line(line)
        out.append(line)
    return "\n".join(out)


def main() -> int:
    text = HTA.read_text(encoding="utf-8")
    marker = '<script language="VBScript">'
    start = text.index(marker)
    end = text.index("</script>", start)
    head = text[: start + len(marker)]
    block = text[start + len(marker) : end]
    tail = text[end:]
    patched = patch_block(block)
    text = head + patched + tail
    text = text.replace("v8.6.2-FIX", "v8.6.3-CHR").replace("v8.6.1-ONE", "v8.6.3-CHR")
    HTA.write_text(text, encoding="utf-8")
    remaining = patched.count("<")
    print("OK v8.6.3-CHR remaining_lt", remaining)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
