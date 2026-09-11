#!/usr/bin/env python3
import json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
usages = json.loads((ROOT/"tools/audit/out/key_usages.json").read_text(encoding="utf-8"))
live = (ROOT/"tradingbot/config/live.py").read_text(encoding="utf-8")
lines = live.splitlines()
flags = []
seen = set()
for i, ln in enumerate(lines):
    m = re.search(r"os\.getenv\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*([^)]+))?\)", ln)
    if not m:
        continue
    env_key = m.group(1)
    default = (m.group(2) or "").strip()
    # config key on same line if dict entry
    cm = re.search(r"['\"]([A-Z0-9_]+)['\"]\s*:", ln)
    cfg_key = cm.group(1) if cm else None
    comments = []
    for j in range(i-1, max(-1, i-5), -1):
        s = lines[j].strip()
        if s.startswith("#"):
            comments.append(s.lstrip("# ").strip())
        elif not s:
            continue
        else:
            break
    comment = " | ".join(reversed(comments))
    # wiring via config key string
    other_files = []
    if cfg_key:
        for x in usages.get(cfg_key, []):
            if x["file"] != "tradingbot/config/live.py":
                other_files.append(x["file"])
    # also env key string references
    for p in (ROOT/"tradingbot").rglob("*.py"):
        if "__pycache__" in p.parts: continue
        rel = p.as_posix()
        if rel == "tradingbot/config/live.py": continue
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if env_key in t or (cfg_key and cfg_key in t):
            if rel not in other_files:
                # only count if not already
                other_files.append(rel)
    other_files = sorted(set(other_files))
    key_id = (env_key, cfg_key, i)
    if key_id in seen:
        continue
    seen.add(key_id)
    flags.append({
        "line": i+1,
        "env_key": env_key,
        "config_key": cfg_key,
        "default_expr": default,
        "nearby_comment": comment,
        "wired_files_outside_live_py": other_files,
        "wired": len(other_files) > 0,
    })

# dedupe by env_key keeping first with config_key preference
by = {}
for f in flags:
    k = f["env_key"]
    if k not in by:
        by[k] = f
    else:
        # merge files
        by[k]["wired_files_outside_live_py"] = sorted(set(by[k]["wired_files_outside_live_py"] + f["wired_files_outside_live_py"]))
        by[k]["wired"] = len(by[k]["wired_files_outside_live_py"]) > 0
        if not by[k]["config_key"] and f["config_key"]:
            by[k]["config_key"] = f["config_key"]
        if not by[k]["nearby_comment"] and f["nearby_comment"]:
            by[k]["nearby_comment"] = f["nearby_comment"]

out = sorted(by.values(), key=lambda x: x["env_key"])
(ROOT/"tools/audit/out/live_flag_inventory.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
for f in out:
    print(f"{f['env_key']}: cfg={f['config_key']} default={f['default_expr'][:50]!r} wired={f['wired']} nfiles={len(f['wired_files_outside_live_py'])}")
    if f["nearby_comment"]:
        print(f"   comment: {f['nearby_comment'][:120]}")
