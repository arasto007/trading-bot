#!/usr/bin/env python3
"""PROJECT_AUDIT_1 static reachability analyzer. tools/audit/ — not production."""
from __future__ import annotations
import ast, json, os, re, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INVENTORY_ROOTS = [ROOT / "tradingbot", ROOT / "engine", ROOT / "scripts"]
ENTRY_MODULES = [
    "tradingbot.__main__",
    "tradingbot.application.live_runner",
    "tradingbot.application.bootstrap",
    "tradingbot.backtest.engine",
]
DOC_SCRIPT_HINTS = [
    "scripts/dashboard_server.py", "scripts/check_live_setup.py",
    "scripts/run_live_watchdog.py", "scripts/status_live.py",
    "scripts/show_meta_stats.py", "scripts/run_backtest.py",
    "scripts/backtest_custom_range.py", "scripts/start_bot.py",
    "scripts/weekend_checklist.py", "scripts/status_snapshot.py",
    "scripts/morning_go_live_check.py", "scripts/diagnose_autotrading.py",
    "scripts/release_mt5_ipc_lock.py", "scripts/fix_mt5_experts_ini.py",
    "scripts/smoke_test_execution.py", "scripts/live_daily_report.py",
    "scripts/demo_proof_status.py", "scripts/train_meta_labeler.py",
    "scripts/scheduled_ml_refresh.py", "scripts/collect_ml_data.py",
    "scripts/verify_ml_live_ready.py", "scripts/run_phase17d_bundle_promotion.py",
    "scripts/build_ml_dataset.py",
]
PROJECT_TOPS = {"tradingbot", "engine", "scripts"}

def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except Exception:
        return str(p)

def module_to_path(mod: str) -> Path | None:
    parts = mod.split(".")
    cand = ROOT.joinpath(*parts)
    if cand.with_suffix(".py").is_file():
        return cand.with_suffix(".py")
    if (cand / "__init__.py").is_file():
        return cand / "__init__.py"
    return None

def path_to_module(p: Path) -> str | None:
    try:
        r = p.resolve().relative_to(ROOT)
    except Exception:
        return None
    if r.suffix != ".py":
        return None
    parts = list(r.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)

def extract_imports(py_path: Path) -> set[str]:
    out: set[str] = set()
    try:
        src = py_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError:
        for m in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", src, re.M):
            name = m.group(1) or m.group(2)
            if name:
                out.add(name.split(",")[0].strip())
        return out
    pkg = path_to_module(py_path)
    pkg_parts = pkg.split(".") if pkg else []
    if py_path.name != "__init__.py" and pkg_parts:
        pkg_parts = pkg_parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and pkg_parts:
                if node.level == 1:
                    base = pkg_parts
                else:
                    base = pkg_parts[: max(0, len(pkg_parts) - (node.level - 1))]
                prefix = ".".join(base)
                if node.module:
                    out.add(f"{prefix}.{node.module}" if prefix else node.module)
                elif prefix:
                    out.add(prefix)
            elif node.module:
                out.add(node.module)
    return out

def discover_script_refs() -> list[str]:
    found = list(DOC_SCRIPT_HINTS)
    start = ROOT / "start"
    if start.is_dir():
        for bat in start.glob("*.bat"):
            text = bat.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"(?:scripts\\|/scripts/|scripts/)([\w./\\-]+\.py)", text, re.I):
                found.append("scripts/" + m.group(1).replace("\\", "/"))
            for m in re.finditer(r"python\s+-m\s+([\w.]+)", text, re.I):
                found.append("MODULE:" + m.group(1))
    doc = ROOT / "دستورات_اجرایی.md"
    if doc.is_file():
        text = doc.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"scripts/[\w./-]+\.py", text):
            found.append(m.group(0))
        for m in re.finditer(r"python\s+-m\s+([\w.]+)", text):
            found.append("MODULE:" + m.group(1))
    return sorted(set(found))

def all_inventory_py() -> dict[str, Path]:
    files: list[Path] = []
    for root in INVENTORY_ROOTS:
        if root.is_dir():
            for p in root.rglob("*.py"):
                if "__pycache__" not in p.parts:
                    files.append(p)
    files.extend(ROOT.glob("*.py"))
    return {rel(p): p for p in files}

def collect_test_refs() -> tuple[set[str], set[str]]:
    modules: set[str] = set()
    paths: set[str] = set()
    path_re = re.compile(r"[\"']((?:tradingbot|engine|scripts)/[\w./-]+\.py)[\"']")
    mod_string_re = re.compile(r"[\"']((?:tradingbot|engine|scripts)(?:\.[\w]+)+)[\"']")
    tests = ROOT / "tests"
    for p in tests.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for imp in extract_imports(p):
            if imp.split(".")[0] in PROJECT_TOPS:
                modules.add(imp)
        for m in path_re.finditer(src):
            paths.add(m.group(1))
        for m in mod_string_re.finditer(src):
            modules.add(m.group(1))
    return modules, paths

def resolve_chain(start_mods: list[str], start_files: list[Path]) -> set[str]:
    reachable: set[str] = set()
    queue: list[Path] = []
    seen: set[Path] = set()

    def enqueue_mod(mod: str) -> None:
        parts = mod.split(".")
        for i in range(len(parts), 0, -1):
            cand = module_to_path(".".join(parts[:i]))
            if cand and cand not in seen:
                queue.append(cand)
                seen.add(cand)
                return

    for m in start_mods:
        if m.split(".")[0] in PROJECT_TOPS:
            enqueue_mod(m)
    for f in start_files:
        if f.is_file() and f not in seen:
            queue.append(f)
            seen.add(f)

    while queue:
        cur = queue.pop(0)
        reachable.add(rel(cur))
        for name in extract_imports(cur):
            top = name.split(".")[0]
            if top not in PROJECT_TOPS:
                continue
            parts = name.split(".")
            for i in range(len(parts), 0, -1):
                p = module_to_path(".".join(parts[:i]))
                if p and p not in seen:
                    seen.add(p)
                    queue.append(p)
            for i in range(1, len(parts)):
                p = module_to_path(".".join(parts[:i]))
                if p and p not in seen:
                    seen.add(p)
                    queue.append(p)
    return reachable

def first_docstring(py_path: Path) -> str:
    try:
        src = py_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        d = ast.get_docstring(tree) or ""
        return " ".join(d.strip().split())[:300]
    except Exception:
        try:
            lines = py_path.read_text(encoding="utf-8", errors="replace").splitlines()[:25]
            comments = []
            for ln in lines:
                s = ln.strip()
                if s.startswith("#"):
                    comments.append(s.lstrip("# ").strip())
                elif comments:
                    break
            return " ".join(comments)[:300]
        except Exception:
            return ""

def is_phase_research(relpath: str) -> bool:
    name = Path(relpath).name.lower()
    if re.match(r"phase\d+[a-z0-9_]*\.py$", name):
        return True
    low = relpath.replace("\\", "/").lower()
    parts = low.split("/")
    for part in parts:
        if re.match(r"phase\d+", part):
            return True
    if "/ml/research/" in low:
        return True
    return False

def bulk_git_last() -> dict[str, dict]:
    """One git rev-list walk mapped to paths — much faster than per-file log."""
    result: dict[str, dict] = {}
    try:
        # format: commit date | subject, then null, then paths null-separated per commit is hard;
        # use --name-only with a marker.
        proc = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:COMMIT\t%ci\t%s", "--",
             "tradingbot", "engine", "scripts", "*.py"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300,
        )
        cur_date = None
        cur_msg = None
        for line in (proc.stdout or "").splitlines():
            if line.startswith("COMMIT\t"):
                _, date, msg = line.split("\t", 2)
                cur_date, cur_msg = date, msg
            elif line.strip() and cur_date is not None:
                path = line.strip().replace("\\", "/")
                if path not in result:
                    result[path] = {"date": cur_date, "message": cur_msg}
    except Exception as e:
        print("git bulk failed", e)
    return result

def main() -> int:
    print("ROOT", ROOT)
    script_refs = discover_script_refs()
    test_mods, test_paths = collect_test_refs()

    runtime_mods = list(ENTRY_MODULES)
    runtime_files: list[Path] = []
    for ref in script_refs:
        if ref.startswith("MODULE:"):
            runtime_mods.append(ref[7:])
        else:
            p = ROOT / ref.replace("\\", "/")
            if p.is_file():
                runtime_files.append(p)

    full_mods = list(runtime_mods) + sorted(test_mods)
    full_files = list(runtime_files)
    for tp in test_paths:
        p = ROOT / tp
        if p.is_file():
            full_files.append(p)

    print("Resolving runtime graph...")
    runtime_reachable = resolve_chain(runtime_mods, runtime_files)
    print("Resolving full (runtime+tests) graph...")
    reachable = resolve_chain(full_mods, full_files)

    # Expand test path mentions into reachable
    for tp in test_paths:
        if (ROOT / tp).is_file():
            reachable.add(tp)

    inventory = all_inventory_py()
    unreachable = sorted(set(inventory) - reachable)

    # test-only refs that are in reachable but not runtime
    test_only_in_reachable = sorted(reachable - runtime_reachable)

    print("Loading git history...")
    gitmap = bulk_git_last()

    classified = []
    for ur in unreachable:
        research = is_phase_research(ur)
        # Check if tests mention this file even if import graph missed it
        mentioned = ur in test_paths or any(
            module_to_path(m) and rel(module_to_path(m)) == ur for m in test_mods
        )
        if mentioned:
            flag = "TEST_ONLY"
        elif research:
            flag = "RESEARCH_ARCHIVE_CANDIDATE"
        else:
            flag = "DEAD_CODE"
        meta = gitmap.get(ur, {})
        classified.append({
            "path": ur,
            "flag": flag,
            "docstring_head": first_docstring(inventory[ur]),
            "last_commit_date": meta.get("date"),
            "last_commit_message": meta.get("message"),
            "in_runtime_graph": False,
            "in_test_refs": mentioned,
        })

    # Also record TEST_ONLY files that ARE reachable via tests but not runtime
    test_only_reachable = []
    for pth in test_only_in_reachable:
        if pth not in inventory:
            continue
        meta = gitmap.get(pth, {})
        test_only_reachable.append({
            "path": pth,
            "flag": "TEST_ONLY",
            "docstring_head": first_docstring(inventory[pth]),
            "last_commit_date": meta.get("date"),
            "last_commit_message": meta.get("message"),
            "in_runtime_graph": False,
            "in_test_refs": True,
            "note": "reachable via tests entry expansion; not in runtime entry graph",
        })

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inventory_count": len(inventory),
        "reachable_count": len(reachable & set(inventory)),
        "unreachable_count": len(unreachable),
        "runtime_reachable_count": len(runtime_reachable & set(inventory)),
        "test_only_reachable_count": len(test_only_reachable),
        "entry_modules": ENTRY_MODULES,
        "script_entry_refs": script_refs,
        "flag_counts_unreachable": {
            "DEAD_CODE": sum(1 for c in classified if c["flag"] == "DEAD_CODE"),
            "RESEARCH_ARCHIVE_CANDIDATE": sum(1 for c in classified if c["flag"] == "RESEARCH_ARCHIVE_CANDIDATE"),
            "TEST_ONLY": sum(1 for c in classified if c["flag"] == "TEST_ONLY"),
        },
    }
    (OUT_DIR / "reachable.json").write_text(json.dumps(sorted(reachable & set(inventory)), indent=2), encoding="utf-8")
    (OUT_DIR / "runtime_reachable.json").write_text(json.dumps(sorted(runtime_reachable & set(inventory)), indent=2), encoding="utf-8")
    (OUT_DIR / "unreachable.json").write_text(json.dumps(classified, indent=2), encoding="utf-8")
    (OUT_DIR / "test_only_reachable.json").write_text(json.dumps(test_only_reachable, indent=2), encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())