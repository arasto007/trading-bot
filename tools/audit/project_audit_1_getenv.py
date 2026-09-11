#!/usr/bin/env python3
"""Scan os.getenv / os.environ usage across repo. tools/audit/ only."""
from __future__ import annotations
import ast, json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)

GETENV_RE = re.compile(
    r"""os\.(?:getenv|environ\.get)\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*([^)]+))?\)"""
)
ENV_IDX_RE = re.compile(r"""os\.environ\[\s*['\"]([^'\"]+)['\"]\s*\]""")

def scan_file(p: Path) -> list[dict]:
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rel = p.resolve().relative_to(ROOT).as_posix()
    hits = []
    for i, line in enumerate(src.splitlines(), 1):
        for m in GETENV_RE.finditer(line):
            default = (m.group(2) or "").strip()
            hits.append({"file": rel, "line": i, "key": m.group(1), "default_expr": default, "kind": "getenv"})
        for m in ENV_IDX_RE.finditer(line):
            hits.append({"file": rel, "line": i, "key": m.group(1), "default_expr": None, "kind": "environ[]"})
    return hits

def main():
    hits = []
    for root_name in ("tradingbot", "engine", "scripts", "tests"):
        root = ROOT / root_name
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            hits.extend(scan_file(p))
    for p in ROOT.glob("*.py"):
        hits.extend(scan_file(p))

    by_key = defaultdict(list)
    for h in hits:
        by_key[h["key"]].append(h)

    # Focus live.py flags
    live_hits = [h for h in hits if h["file"] == "tradingbot/config/live.py"]

    inventory = []
    for key, locs in sorted(by_key.items()):
        files = sorted({x["file"] for x in locs})
        defaults = sorted({x["default_expr"] for x in locs if x["default_expr"]})
        in_live = any(x["file"] == "tradingbot/config/live.py" for x in locs)
        other = [f for f in files if f != "tradingbot/config/live.py"]
        inventory.append({
            "key": key,
            "defaults": defaults,
            "defined_or_read_in_live_py": in_live,
            "locations": locs,
            "other_files": other,
            "wired_elsewhere": len(other) > 0,
            "location_count": len(locs),
        })

    out = {
        "total_getenv_sites": len(hits),
        "unique_keys": len(by_key),
        "live_py_sites": live_hits,
        "inventory": inventory,
    }
    (OUT / "getenv_inventory.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"sites={len(hits)} keys={len(by_key)}")
    # print live-centric summary
    for item in inventory:
        if item["defined_or_read_in_live_py"]:
            print(f"{item['key']}: defaults={item['defaults']} wired_elsewhere={item['wired_elsewhere']} others={len(item['other_files'])}")

if __name__ == "__main__":
    main()