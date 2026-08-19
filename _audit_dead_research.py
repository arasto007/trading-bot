"""One-off audit: research modules not reachable from live path."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIVE_SEEDS = [
    ROOT / "tradingbot" / "application" / "live_runner.py",
    ROOT / "start",
    ROOT / "tradingbot" / "kernel" / "trading_kernel.py",
]


def module_from_path(p: Path) -> str:
    return ".".join(p.relative_to(ROOT).with_suffix("").parts)


def resolve_import(module: str) -> list[Path]:
    parts = module.split(".")
    out: list[Path] = []
    cur = ROOT
    for i, part in enumerate(parts):
        cur = cur / part
        if i == len(parts) - 1:
            py = cur.with_suffix(".py")
            init = cur / "__init__.py"
            if py.is_file():
                out.append(py)
            elif init.is_file():
                out.append(init)
        elif not cur.is_dir():
            return out
    return out


def parse_imports(src: str) -> set[str]:
    mods: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return mods
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
    return mods


def bfs_live_modules() -> set[str]:
    queue: list[Path] = []
    seen_files: set[str] = set()
    live_modules: set[str] = set()

    def add(p: Path) -> None:
        key = str(p.resolve())
        if key in seen_files or not p.is_file():
            return
        seen_files.add(key)
        queue.append(p)
        live_modules.add(module_from_path(p))

    for seed in LIVE_SEEDS:
        if seed.is_file():
            add(seed)
        elif seed.is_dir():
            for p in seed.rglob("*.py"):
                add(p)

    while queue:
        p = queue.pop(0)
        try:
            src = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for imp in parse_imports(src):
            if not (imp.startswith("tradingbot.") or imp == "tradingbot" or imp.startswith("engine.")):
                continue
            for target in resolve_import(imp):
                add(target)
    return live_modules


def main() -> None:
    live_modules = bfs_live_modules()
    research_dir = ROOT / "tradingbot" / "ml" / "research"
    dead: list[str] = []
    live: list[str] = []
    for py in sorted(research_dir.rglob("*.py")):
        if py.name == "__init__.py":
            continue
        mod = module_from_path(py)
        if mod in live_modules:
            live.append(mod)
        else:
            dead.append(mod)
    print(f"LIVE_MODULES={len(live_modules)}")
    print(f"RESEARCH_LIVE={len(live)}")
    print(f"RESEARCH_DEAD={len(dead)}")
    print("---DEAD---")
    for m in dead:
        print(m)
    print("---LIVE_RESEARCH---")
    for m in live:
        print(m)


if __name__ == "__main__":
    main()
