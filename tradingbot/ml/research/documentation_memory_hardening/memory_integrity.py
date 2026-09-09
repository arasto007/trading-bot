"""Answer ChatGPT memory questions from canonical docs only. No production imports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
ENTRY = "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
BOOT = "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md"
DOC_PATH = re.compile(r"docs_v2/[A-Za-z0-9_./-]+\.md")


def _load(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def allowed_corpus() -> tuple[str, list[str]]:
    seeds = [ENTRY, BOOT]
    seen: set[str] = set()
    ordered: list[str] = []
    for rel in seeds:
        if rel in seen:
            continue
        seen.add(rel)
        ordered.append(rel)
        text = _load(rel)
        for ref in DOC_PATH.findall(text):
            if ref not in seen:
                seen.add(ref)
                ordered.append(ref)
    blob = "\n\n".join(_load(rel) for rel in ordered)
    return blob, ordered


def _has(blob: str, *needles: str) -> bool:
    return all(n in blob for n in needles)


def evaluate_questions(blob: str) -> list[dict[str, Any]]:
    """Documentation-only checks. Missing needle => DOCUMENTATION_GAP."""
    checks: list[tuple[str, bool, str]] = [
        ("1_default_runs", _has(blob, "Price Action", "MultiEngineRouterRegistry"), "PA via router"),
        ("2_symbol", _has(blob, "XAUUSD_i"), "XAUUSD_i"),
        ("3_timeframe", _has(blob, "5m") or _has(blob, "M5"), "M5/5m"),
        ("4_strategy", _has(blob, "priceaction"), "priceaction"),
        ("5_preset", _has(blob, "gold_ny_sweep"), "gold_ny_sweep"),
        ("6_live_path", _has(blob, "START_BOT.bat", "RiskGate.evaluate", "Mt5ExecutionAdapter.execute"), "full path"),
        ("7_ml_active", _has(blob, "USE_ML_KERNEL") and ("false" in blob.lower() or "off" in blob.lower()), "ML off"),
        ("8_v41_status", _has(blob, "trend_rf_v41") and ("inactive" in blob.lower() or "C" in blob), "v41 C/inactive"),
        ("9_v41_factor", _has(blob, "1.0") and _has(blob, "engine_calibration_factor"), "1.0"),
        ("10_riskgate_role", _has(blob, "RiskGate.evaluate") and "mandatory" in blob.lower() or _has(blob, "RiskGate"), "RiskGate"),
        ("11_missing_spread", _has(blob, "999"), "tick missing 999"),
        ("12_boundary", _has(blob, "PRODUCTION") and _has(blob, "RESEARCH") or _has(blob, "ml/research"), "boundary"),
        ("13_unknowns", _has(blob, "UNKNOWN") and ("XAUUSD_i" in blob), "unknowns"),
        ("14_contradictions", _has(blob, "london_sweep") and _has(blob, "NY 15"), "CX london/NY"),
        ("15_production_sensitive", _has(blob, "production-affecting") or _has(blob, "PRODUCTION-CRITICAL") or _has(blob, "RiskGate"), "sensitive"),
        ("16_doc_update", _has(blob, "DOCUMENTATION_UPDATE_PROTOCOL") or _has(blob, "DOCUMENTATION_IMPACT_MAP"), "update protocol"),
        ("17_broker_costs", _has(blob, "class-A") or _has(blob, "round-trip") or _has(blob, "Commission"), "costs unknown"),
        ("18_operator_verify", _has(blob, ".env") and _has(blob, "UNKNOWN"), "operator env"),
        ("19_safety", _has(blob, "PA_PRODUCTION_LOCK") and _has(blob, "Do not"), "locks"),
        ("20_start_reading", _has(blob, "PROJECT_SOURCE_OF_TRUTH.md") and _has(blob, "CHATGPT_BOOTSTRAP.md"), "read order"),
    ]
    rows = []
    for qid, ok, note in checks:
        rows.append(
            {
                "id": qid,
                "ok": ok,
                "classification": "DOCUMENTED" if ok else "DOCUMENTATION_GAP",
                "note": note,
            }
        )
    return rows


def run_memory_integrity(*, write_reports: bool = True) -> dict[str, Any]:
    blob, files = allowed_corpus()
    questions = evaluate_questions(blob)
    gaps = [q for q in questions if not q["ok"]]
    payload = {
        "phase": "1.5.78",
        "production_source_read": False,
        "files_read": files,
        "questions": questions,
        "gaps": gaps,
        "ok": not gaps,
    }
    if write_reports:
        out = ROOT / "data" / "ml" / "reports" / "documentation_memory_hardening"
        out.mkdir(parents=True, exist_ok=True)
        (out / "memory_integrity.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
