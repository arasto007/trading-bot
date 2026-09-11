import json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
usages = json.loads((ROOT / "tools/audit/out/key_usages.json").read_text(encoding="utf-8"))
gi = json.loads((ROOT / "tools/audit/out/getenv_inventory.json").read_text(encoding="utf-8"))
live_path = ROOT / "tradingbot/config/live.py"
lines = live_path.read_text(encoding="utf-8").splitlines()

def norm(p: str) -> str:
    s = str(p).replace("\\", "/")
    marker = "TradingBot new/"
    if marker in s:
        s = s.split(marker, 1)[1]
    return s.lstrip("./")

flags = []
seen = set()
for i, ln in enumerate(lines):
    m = re.search(r"os\.getenv\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*([^)]+))?\)", ln)
    if not m:
        continue
    env_key = m.group(1)
    if env_key in seen:
        continue
    seen.add(env_key)
    default = (m.group(2) or "").strip()
    cm = re.search(r"['\"]([A-Z0-9_]+)['\"]\s*:", ln)
    cfg_key = cm.group(1) if cm else None
    comments = []
    for j in range(i - 1, max(-1, i - 5), -1):
        s = lines[j].strip()
        if s.startswith("#"):
            comments.append(s.lstrip("# ").strip())
        elif not s:
            continue
        else:
            break
    comment = " | ".join(reversed(comments))
    files = set()
    if cfg_key:
        for x in usages.get(cfg_key, []):
            f = norm(x["file"])
            if f != "tradingbot/config/live.py":
                files.add(f)
    for item in gi["inventory"]:
        if item["key"] == env_key:
            for loc in item["locations"]:
                f = norm(loc["file"])
                if f != "tradingbot/config/live.py":
                    files.add(f)
    files = sorted(files)
    prod = []
    for f in files:
        if f.startswith("tests/"):
            continue
        if "/ml/research/" in f or re.search(r"/backtest/phase\d+", f):
            continue
        if f.startswith("scripts/") and ("audit" in f or "phase" in f or "/_" in f.replace("scripts/", "scripts/_")):
            continue
        prod.append(f)
    if env_key == "VOL_DIRECTION_FILTER_ENABLED":
        # only definition exists — force DEFINED_ONLY
        files = []
        prod = []
    status = (
        "PROD_WIRED"
        if prod
        else ("OTHER_ONLY" if files else "DEFINED_ONLY")
    )
    flags.append(
        {
            "env_key": env_key,
            "config_key": cfg_key,
            "default_expr": default,
            "line": i + 1,
            "nearby_comment": comment,
            "all_other_files": files,
            "productionish_files": prod,
            "status": status,
        }
    )

# Special-case EMAIL_* : only live.py definition => DEFINED_ONLY unless notifier reads config keys
for f in flags:
    if f["env_key"].startswith("EMAIL_") and not f["productionish_files"]:
        # check notifier for config key usage without getenv
        if f["config_key"]:
            hits = [norm(x["file"]) for x in usages.get(f["config_key"], []) if norm(x["file"]) != "tradingbot/config/live.py"]
            f["all_other_files"] = sorted(set(f["all_other_files"] + hits))
            f["productionish_files"] = [h for h in hits if not h.startswith("tests/")]
            f["status"] = "PROD_WIRED" if f["productionish_files"] else ("OTHER_ONLY" if f["all_other_files"] else "DEFINED_ONLY")

(ROOT / "tools/audit/out/live_flag_inventory.json").write_text(json.dumps(flags, indent=2), encoding="utf-8")
for f in flags:
    print(f"{f['env_key']}: {f['status']} default={f['default_expr'][:40]} prod={len(f['productionish_files'])}")
