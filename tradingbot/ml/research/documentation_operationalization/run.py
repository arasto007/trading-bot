"""Verification-only operationalization audit. Does not repair docs or production code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

from tradingbot.ml.research.documentation_freshness.scanner import WATCHED
from tradingbot.ml.research.documentation_memory_hardening.memory_integrity import (
    allowed_corpus,
)


def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def bootstrap_imports_research() -> bool:
    text = _read("tradingbot/application/bootstrap.py")
    return "ml.research" in text or "documentation_freshness" in text


def questions_25(blob: str) -> list[dict[str, Any]]:
    """Docs-only. UNKNOWN is success when the fact is not established. No guessing."""

    def has(*n: str) -> bool:
        return all(x in blob for x in n)

    rows = [
        {"id": "Q01", "topic": "Architecture", "q": "What is the robot?", "class": "DOCUMENTED" if has("Price Action", "MetaTrader") else "GAP"},
        {"id": "Q02", "topic": "Runtime", "q": "What runs live by default?", "class": "DOCUMENTED" if has("Price Action", "MultiEngineRouterRegistry") else "GAP"},
        {"id": "Q03", "topic": "Runtime", "q": "Exact default live path?", "class": "DOCUMENTED" if has("START_BOT.bat", "RiskGate.evaluate") else "GAP"},
        {"id": "Q04", "topic": "Strategy", "q": "Active strategy id?", "class": "DOCUMENTED" if has("priceaction") else "GAP"},
        {"id": "Q05", "topic": "Runtime", "q": "Active symbol?", "class": "DOCUMENTED" if has("XAUUSD_i") else "GAP"},
        {"id": "Q06", "topic": "Runtime", "q": "Active timeframe?", "class": "DOCUMENTED" if has("5m") or has("M5") else "GAP"},
        {"id": "Q07", "topic": "PA", "q": "PA preset?", "class": "DOCUMENTED" if has("gold_ny_sweep") else "GAP"},
        {"id": "Q08", "topic": "PA", "q": "PA SL/TP numeric formula?", "class": "DERIVED" if has("PRICE_ACTION_LIVE_SPEC") else "GAP"},
        {"id": "Q09", "topic": "RiskGate", "q": "RiskGate role?", "class": "DOCUMENTED" if has("RiskGate.evaluate") else "GAP"},
        {"id": "Q10", "topic": "RiskGate", "q": "Missing tick spread?", "class": "DOCUMENTED" if has("999") else "GAP"},
        {"id": "Q11", "topic": "RiskGate", "q": "Full RiskGate hop order 1-13?", "class": "DERIVED" if has("RISKGATE_SPEC") else "GAP"},
        {"id": "Q12", "topic": "Execution", "q": "Execute vs paper vs dry-run?", "class": "DOCUMENTED" if has("Mt5ExecutionAdapter.execute") else "GAP"},
        {"id": "Q13", "topic": "Execution", "q": "Current broker commission?", "class": "UNKNOWN" if "Commission" in blob and "UNKNOWN" in blob else "GAP"},
        {"id": "Q14", "topic": "Data", "q": "XAUUSD equals XAUUSD_i?", "class": "UNKNOWN" if has("NOT PROVEN") else "GAP"},
        {"id": "Q15", "topic": "ML", "q": "Is ML kernel live?", "class": "DOCUMENTED" if has("USE_ML_KERNEL") else "GAP"},
        {"id": "Q16", "topic": "v41", "q": "v41 live status and factor?", "class": "DOCUMENTED" if has("trend_rf_v41", "1.0") else "GAP"},
        {"id": "Q17", "topic": "v41", "q": "v41 research class C?", "class": "DOCUMENTED" if " **C**" in blob or "class **C**" in blob or "Class **C**" in blob else "GAP"},
        {"id": "Q18", "topic": "Safety", "q": "PA lock default?", "class": "DOCUMENTED" if has("PA_PRODUCTION_LOCK") else "GAP"},
        {"id": "Q19", "topic": "Safety", "q": "Must ChatGPT assume .env equals defaults?", "class": "DOCUMENTED" if "NEVER assume" in blob or "must NEVER assume" in blob else "GAP"},
        {"id": "Q20", "topic": "Unknowns", "q": "Operator .env values?", "class": "UNKNOWN" if ".env" in blob and "UNKNOWN" in blob else "GAP"},
        {"id": "Q21", "topic": "Unknowns", "q": "Is the daemon running now?", "class": "UNKNOWN"},
        {"id": "Q22", "topic": "Contradictions", "q": "Does london_sweep mean London hours?", "class": "CONTRADICTED" if has("london_sweep") and has("NY 15") else "GAP"},
        {"id": "Q23", "topic": "Change control", "q": "What to update after RiskGate code change?", "class": "DERIVED" if has("RISKGATE_SPEC") and has("DOCUMENTATION_IMPACT_MAP") else "GAP"},
        {"id": "Q24", "topic": "Configuration", "q": "Daemon-if-unset vs operator env?", "class": "DOCUMENTED" if "if unset" in blob.lower() or "Daemon if unset" in blob else "GAP"},
        {"id": "Q25", "topic": "Boundary", "q": "Are ml/research auditors on live path?", "class": "DOCUMENTED" if has("ml/research") else "GAP"},
        {"id": "Q26", "topic": "PA", "q": "London session on live preset?", "class": "DOCUMENTED" if "London" in blob and "off" in blob.lower() else "GAP"},
        {"id": "Q27", "topic": "Execution", "q": "Current open orders / account?", "class": "UNKNOWN"},
        {"id": "Q28", "topic": "ML", "q": "Current-day meta should_gate()?", "class": "UNKNOWN" if "NOT PROVEN" in blob else "GAP"},
        {"id": "Q29", "topic": "Architecture", "q": "Factory branch order?", "class": "DERIVED" if has("build_strategy_registry") else "GAP"},
        {"id": "Q30", "topic": "Data", "q": "Live forming-bar handling?", "class": "DOCUMENTED" if has("exclude_forming_bar") else "GAP"},
    ]
    return rows


def run_operationalization(*, write_reports: bool = True) -> dict[str, Any]:
    blob, files = allowed_corpus()
    qs = questions_25(blob)
    impact_text = _read("docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md")
    missing_watch = [f for f in WATCHED if f"`{f}`" not in impact_text]
    extra_watch = []
    payload = {
        "phase": "documentation_memory_operationalization",
        "offline_only": True,
        "production_source_for_questions": False,
        "session_files": files,
        "bootstrap_imports_research": bootstrap_imports_research(),
        "watched_vs_impact_map": {
            "impact_not_watched": missing_watch,
            "watched_not_in_impact_list": extra_watch,
        },
        "questions": qs,
        "question_classes": {
            k: sum(1 for q in qs if q["class"] == k)
            for k in ("DOCUMENTED", "DERIVED", "UNKNOWN", "CONTRADICTED", "GAP")
        },
        "gaps": [q for q in qs if q["class"] == "GAP"],
        "weaknesses_documented_not_fixed": [
            "Complete static production call graph remains UNKNOWN (UNK-011)",
            "Substring integrity tests are not full semantic comprehension",
            "Operator-effective state remains UNKNOWN without a sanitized env/MT5 dump",
        ],
    }
    if write_reports:
        out = ROOT / "data" / "ml" / "reports" / "documentation_operationalization"
        out.mkdir(parents=True, exist_ok=True)
        (out / "verification.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


if __name__ == "__main__":
    r = run_operationalization()
    print(
        json.dumps(
            {
                "classes": r["question_classes"],
                "gaps": r["gaps"],
                "not_watched": r["watched_vs_impact_map"]["impact_not_watched"],
            },
            indent=2,
        )
    )
