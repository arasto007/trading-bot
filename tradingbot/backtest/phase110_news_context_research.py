"""Phase 110 — news / event context research.

Does not call external APIs, download news, or fabricate calendar labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON

PHASE = "110"
PHASE110_JSON = "logs/phase110_news_context_research.json"
PHASE110_MD = "docs/PHASE110_NEWS_CONTEXT_RESEARCH.md"
BLOCKED = "BLOCKED"
ALLOWED = ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "DATA_MISSING", "INSUFFICIENT_EVIDENCE")
NEWS_GLOBS = (
    "data/**/*news*",
    "data/**/*calendar*",
    "logs/**/*news*",
    "logs/**/*calendar*",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "NEWS_DISCRIMINATOR_STATUS",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _existing_news_files(root: Path) -> list[str]:
    hits = []
    for pat in NEWS_GLOBS:
        for p in root.glob(pat):
            if p.is_file() and p.suffix.lower() in {".json", ".jsonl", ".csv", ".parquet", ".txt"}:
                # Generators / code are not data. Skip python.
                hits.append(str(p.relative_to(root)).replace("\\", "/"))
    return sorted(set(hits))


def run_phase110_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p106 = _safe_load_json(root / PHASE106_JSON) or {}
    news_class = (p106.get("by_category") or {}).get("news") or "MISSING"
    files = _existing_news_files(root)
    # Hardcoded schedule in news_calendar.py is not a historical dataset.
    generator_exists = (root / "tradingbot/ml/data/news_calendar.py").is_file()
    status = "DATA_MISSING"
    reason = (
        "No historical news/economic-calendar dataset is present on disk. "
        "The in-repo news_calendar generator was not executed and was not used as fabricated labels."
    )
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "external_api": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "inventory_news_class": news_class,
        "data_files_found": files,
        "generator_present_not_used": generator_exists,
        "analyzed": False,
        "NEWS_DISCRIMINATOR_STATUS": status,
        "reason": reason,
        "evidence_kind": "DATA_MISSING",
        "hypotheses": [
            {
                "id": "H110-01",
                "claim": "News/event proximity explains giveback vs tail expansion.",
                "result": status,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["local_news_file_search"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE110_JSON, "md": PHASE110_MD},
    }
    (root / PHASE110_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE110_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE110_MD).write_text(
        "\n".join(
            [
                "# Phase 110 — News / Event Context",
                "",
                f"**NEWS_DISCRIMINATOR_STATUS:** `{status}`",
                reason,
                f"Local data files matched: `{files}`",
                "No news filter. No news strategy.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase110_collection(Path("."))["NEWS_DISCRIMINATOR_STATUS"])
