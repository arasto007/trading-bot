#!/usr/bin/env python3

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "memory"

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
}

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".bat",
    ".ps1",
    ".vbs",
}

def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue

        if any(part in EXCLUDED_DIRS for part in p.parts):
            continue

        if p.suffix.lower() in CODE_EXTENSIONS:
            yield p


def analyze_python(path: Path):
    result = {
        "file": rel(path),
        "imports": [],
        "classes": [],
        "functions": [],
        "entrypoints": [],
    }

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except Exception as exc:
        result["parse_error"] = str(exc)
        return result

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for name in node.names:
                result["imports"].append(name.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            result["imports"].append(module)

        elif isinstance(node, ast.ClassDef):
            result["classes"].append({
                "name": node.name,
                "line": node.lineno,
            })

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append({
                "name": node.name,
                "line": node.lineno,
                "async": isinstance(node, ast.AsyncFunctionDef),
            })

        elif isinstance(node, ast.If):
            try:
                is_main = (
                    isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "__name__"
                )
            except Exception:
                is_main = False

            if is_main:
                result["entrypoints"].append({
                    "type": "python_main_guard",
                    "line": node.lineno,
                })

    return result


def main():
    MEMORY.mkdir(parents=True, exist_ok=True)

    files = sorted(iter_files(), key=lambda p: rel(p))

    project_index = []
    module_map = {}
    class_index = []
    function_index = []
    import_graph = {}
    runtime_entrypoints = []

    for path in files:
        relative = rel(path)

        info = {
            "file": relative,
            "extension": path.suffix.lower(),
            "size_bytes": path.stat().st_size,
        }

        if path.suffix.lower() == ".py":
            analysis = analyze_python(path)

            info.update({
                "imports": analysis.get("imports", []),
                "classes": analysis.get("classes", []),
                "functions": analysis.get("functions", []),
            })

            module_map[relative] = {
                "imports": analysis.get("imports", []),
                "classes": analysis.get("classes", []),
                "functions": analysis.get("functions", []),
            }

            import_graph[relative] = analysis.get("imports", [])

            for cls in analysis.get("classes", []):
                class_index.append({
                    "file": relative,
                    **cls,
                })

            for fn in analysis.get("functions", []):
                function_index.append({
                    "file": relative,
                    **fn,
                })

            for entry in analysis.get("entrypoints", []):
                runtime_entrypoints.append({
                    "file": relative,
                    **entry,
                })

        else:
            module_map[relative] = {
                "imports": [],
                "classes": [],
                "functions": [],
            }

        project_index.append(info)

    def write_json(name, data):
        path = MEMORY / name
        path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"CREATED: {path}")

    write_json("project_index.json", {
        "project_root": str(ROOT),
        "file_count": len(project_index),
        "files": project_index,
    })

    write_json("module_map.json", module_map)
    write_json("class_index.json", class_index)
    write_json("function_index.json", function_index)
    write_json("import_graph.json", import_graph)
    write_json("runtime_entrypoints.json", runtime_entrypoints)

    print()
    print("========================================")
    print("PROJECT MEMORY BUILD COMPLETE")
    print("========================================")
    print(f"Files:       {len(project_index)}")
    print(f"Classes:     {len(class_index)}")
    print(f"Functions:   {len(function_index)}")
    print(f"Entrypoints: {len(runtime_entrypoints)}")
    print(f"Memory dir:  {MEMORY}")
    print("========================================")


if __name__ == "__main__":
    main()
