#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from collections import Counter

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

TEST_DIRS = {
    "tests",
    "test",
    "testing",
}

RESEARCH_MARKERS = {
    "research",
    "investigation",
    "forensic",
    "audit",
    "discovery",
    "analysis",
}

LEGACY_MARKERS = {
    "legacy",
    "obsolete",
    "deprecated",
    "old",
    "backup",
}

RUNTIME_MARKERS = {
    "run_live",
    "live_runner",
    "execution",
    "executor",
    "trading_kernel",
    "risk_gate",
    "broker",
    "mt5",
    "order",
    "position",
}

RISK_MARKERS = {
    "risk_gate",
    "risk",
    "kill_switch",
    "drawdown",
    "position_sizer",
    "risk_manager",
}

ML_MARKERS = {
    "ml",
    "model",
    "models",
    "training",
    "trainer",
    "classifier",
    "predict",
    "feature",
    "features",
    "dataset",
    "label",
    "transformer",
    "xgboost",
    "lightgbm",
    "dqn",
    "ppo",
}

DATA_MARKERS = {
    "data",
    "dataset",
    "collector",
    "feed",
    "cache",
    "parquet",
    "tick",
    "ohlc",
    "market_data",
}

TOOL_MARKERS = {
    "scripts",
    "tools",
    "build_",
    "check_",
    "fix_",
    "generate_",
    "audit_",
    "diagnostic",
    "diag",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def normalized_parts(path: Path):
    return {
        part.lower()
        for part in Path(rel(path)).parts
    }


def path_text(path: Path) -> str:
    return rel(path).lower()


def classify(path: Path):
    r = rel(path)
    low = r.lower()
    parts = normalized_parts(path)
    name = path.name.lower()

    reasons = []
    scores = Counter()

    # ---------------------------------------------------------
    # TEST
    # ---------------------------------------------------------
    if any(part in TEST_DIRS for part in parts):
        scores["TEST"] += 100
        reasons.append("inside test directory")

    if name.startswith("test_") or name.endswith("_test.py"):
        scores["TEST"] += 80
        reasons.append("test filename")

    # ---------------------------------------------------------
    # HISTORICAL / RESEARCH
    # ---------------------------------------------------------
    if "research" in parts:
        scores["RESEARCH"] += 100
        reasons.append("inside research tree")

    if any(marker in low for marker in RESEARCH_MARKERS):
        scores["RESEARCH"] += 40
        reasons.append("research/investigation marker")

    if any(marker in low for marker in LEGACY_MARKERS):
        scores["LEGACY"] += 80
        reasons.append("legacy/obsolete marker")

    # ---------------------------------------------------------
    # ACTIVE RUNTIME
    # ---------------------------------------------------------
    if "tradingbot" in parts:
        scores["ACTIVE_CORE"] += 30
        reasons.append("inside tradingbot package")

    if any(marker in low for marker in RUNTIME_MARKERS):
        scores["ACTIVE_RUNTIME"] += 35
        reasons.append("runtime marker")

    # ---------------------------------------------------------
    # RISK
    # ---------------------------------------------------------
    if any(marker in low for marker in RISK_MARKERS):
        scores["ACTIVE_RISK"] += 60
        reasons.append("risk component marker")

    # ---------------------------------------------------------
    # ML
    # ---------------------------------------------------------
    if "ml" in parts:
        scores["ACTIVE_ML"] += 50
        reasons.append("inside ML tree")

    if any(marker in low for marker in ML_MARKERS):
        scores["ACTIVE_ML"] += 25
        reasons.append("ML marker")

    # ---------------------------------------------------------
    # DATA
    # ---------------------------------------------------------
    if "data" in parts:
        scores["ACTIVE_DATA"] += 50
        reasons.append("inside data tree")

    if any(marker in low for marker in DATA_MARKERS):
        scores["ACTIVE_DATA"] += 20
        reasons.append("data marker")

    # ---------------------------------------------------------
    # TOOLING
    # ---------------------------------------------------------
    if "scripts" in parts or "tools" in parts:
        scores["TOOLING"] += 50
        reasons.append("inside scripts/tools")

    if any(marker in low for marker in TOOL_MARKERS):
        scores["TOOLING"] += 20
        reasons.append("tool marker")

    # ---------------------------------------------------------
    # STARTUP / BAT / VBS
    # ---------------------------------------------------------
    if path.suffix.lower() in {".bat", ".vbs", ".ps1"}:
        scores["TOOLING"] += 20
        reasons.append("launcher/script file")

    if "start" in parts:
        scores["ACTIVE_RUNTIME"] += 60
        reasons.append("inside start directory")

    # ---------------------------------------------------------
    # DOC / LOG / OTHER
    # ---------------------------------------------------------
    if "docs" in parts:
        scores["DOCUMENTATION"] += 100
        reasons.append("inside docs")

    if "logs" in parts:
        scores["HISTORICAL_LOG"] += 100
        reasons.append("inside logs")

    # ---------------------------------------------------------
    # SPECIAL ACTIVE CORE FILES
    # ---------------------------------------------------------
    core_names = {
        "risk_gate.py",
        "trading_kernel.py",
        "live_runner.py",
        "execution_engine.py",
        "broker.py",
        "order_manager.py",
        "position_manager.py",
    }

    if name in core_names:
        scores["ACTIVE_CORE"] += 150
        reasons.append("known core/runtime filename")

    # ---------------------------------------------------------
    # FINAL CATEGORY
    # ---------------------------------------------------------
    if not scores:
        category = "UNKNOWN"
        confidence = 0.20
    else:
        category, score = scores.most_common(1)[0]
        second = scores.most_common(2)[1][1] if len(scores) > 1 else 0

        confidence = min(
            0.99,
            max(
                0.25,
                0.50 + min(score, 100) / 200 - second / 400
            )
        )

    # Status
    if category in {"RESEARCH", "HISTORICAL_LOG", "LEGACY"}:
        status = "HISTORICAL"

    elif category == "TEST":
        status = "TEST"

    elif category == "UNKNOWN":
        status = "UNKNOWN"

    elif category in {
        "ACTIVE_CORE",
        "ACTIVE_RUNTIME",
        "ACTIVE_RISK",
        "ACTIVE_ML",
        "ACTIVE_DATA",
    }:
        status = "CANDIDATE_ACTIVE"

    else:
        status = "SUPPORTING"

    return {
        "file": r,
        "category": category,
        "status": status,
        "confidence": round(confidence, 3),
        "reasons": reasons,
        "scores": dict(scores),
    }


def iter_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue

        if any(part in EXCLUDED_DIRS for part in p.parts):
            continue

        if p.suffix.lower() not in CODE_EXTENSIONS:
            continue

        yield p


def main():
    MEMORY.mkdir(parents=True, exist_ok=True)

    files = sorted(iter_files(), key=rel)

    results = [classify(p) for p in files]

    category_counts = Counter(x["category"] for x in results)
    status_counts = Counter(x["status"] for x in results)

    # ---------------------------------------------------------
    # Full classification
    # ---------------------------------------------------------
    classification = {
        "project_root": str(ROOT),
        "total_files": len(results),
        "categories": dict(category_counts),
        "statuses": dict(status_counts),
        "files": results,
    }

    # ---------------------------------------------------------
    # Active candidates
    # ---------------------------------------------------------
    active_candidates = [
        x for x in results
        if x["status"] == "CANDIDATE_ACTIVE"
    ]

    # ---------------------------------------------------------
    # Historical / research
    # ---------------------------------------------------------
    historical = [
        x for x in results
        if x["status"] == "HISTORICAL"
    ]

    # ---------------------------------------------------------
    # Unknown
    # ---------------------------------------------------------
    unknown = [
        x for x in results
        if x["status"] == "UNKNOWN"
    ]

    # ---------------------------------------------------------
    # High confidence active
    # ---------------------------------------------------------
    high_confidence_active = [
        x for x in active_candidates
        if x["confidence"] >= 0.75
    ]

    def write(name, data):
        p = MEMORY / name
        p.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("CREATED:", p)

    write("classification.json", classification)

    write(
        "active_candidates.json",
        {
            "count": len(active_candidates),
            "files": active_candidates,
        },
    )

    write(
        "high_confidence_active.json",
        {
            "count": len(high_confidence_active),
            "files": high_confidence_active,
        },
    )

    write(
        "historical_files.json",
        {
            "count": len(historical),
            "files": historical,
        },
    )

    write(
        "unknown_files.json",
        {
            "count": len(unknown),
            "files": unknown,
        },
    )

    # ---------------------------------------------------------
    # Human-readable summary
    # ---------------------------------------------------------
    summary = MEMORY / "classification_summary.md"

    lines = []

    lines.append("# Project Classification Summary")
    lines.append("")
    lines.append(f"- Total analyzed files: **{len(results)}**")
    lines.append("")

    lines.append("## Categories")
    lines.append("")

    for category, count in category_counts.most_common():
        lines.append(f"- `{category}`: **{count}**")

    lines.append("")

    lines.append("## Status")
    lines.append("")

    for status, count in status_counts.most_common():
        lines.append(f"- `{status}`: **{count}**")

    lines.append("")

    lines.append("## High Confidence Active Candidates")
    lines.append("")

    for item in sorted(
        high_confidence_active,
        key=lambda x: (-x["confidence"], x["file"])
    )[:100]:
        lines.append(
            f"- `{item['file']}` — "
            f"{item['category']} — "
            f"{item['confidence']}"
        )

    lines.append("")

    lines.append("## Unknown Files")
    lines.append("")

    for item in sorted(
        unknown,
        key=lambda x: x["file"]
    )[:100]:
        lines.append(f"- `{item['file']}`")

    summary.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("CREATED:", summary)

    print()
    print("========================================")
    print("PROJECT CLASSIFICATION COMPLETE")
    print("========================================")
    print("Files:", len(results))
    print()
    print("CATEGORIES:")

    for category, count in category_counts.most_common():
        print(f"  {category:22} {count}")

    print()
    print("STATUS:")

    for status, count in status_counts.most_common():
        print(f"  {status:22} {count}")

    print()
    print("High confidence active:", len(high_confidence_active))
    print("Historical:", len(historical))
    print("Unknown:", len(unknown))
    print()
    print("Memory:", MEMORY)
    print("========================================")


if __name__ == "__main__":
    main()
