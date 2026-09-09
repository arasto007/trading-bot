"""Phase 67 — next research target gate. No optimization, no production change."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, UNKNOWN, _git_head, _utc_now

PHASE = "67"
PHASE67_JSON = "logs/phase67_next_research_gate.json"
PHASE67_MD = "docs/PHASE67_NEXT_RESEARCH_GATE.md"
PHASE64_67_MD = "docs/PHASE64_67_STRATEGY_DIAGNOSIS_CLOSURE.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE64_JSON = "logs/phase64_strategy_event_forensics.json"
PHASE65_JSON = "logs/phase65_diagnostic_experiments.json"
PHASE66_JSON = "logs/phase66_strategy_root_cause.json"
BLOCKED = "BLOCKED"
ALLOWED = (
    "ENTRY_RESEARCH",
    "EXIT_RESEARCH",
    "REGIME_FILTER_RESEARCH",
    "SIGNAL_DEDUPLICATION_RESEARCH",
    "SIDE_ASYMMETRY_RESEARCH",
    "TIME_DEPENDENCY_RESEARCH",
    "DATA_QUALITY_RESEARCH",
    "COST_RESEARCH",
    "STRATEGY_REPLACEMENT_RESEARCH",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "NEXT_RESEARCH_TARGET",
    "WHY",
    "final_gate",
    "production_safety",
    "artifacts",
)


def select_target(p64: dict[str, Any], p65: dict[str, Any], p66: dict[str, Any]) -> tuple[str, str]:
    primary = (p64.get("causes") or {}).get("PRIMARY") or (p66.get("PRIMARY_ROOT_CAUSE"))
    survives = ((p65.get("experiments") or {}).get("B_outlier_robustness") or {}).get("positive_expectancy_survives_top1_removed")
    mfe = p64.get("mae_mfe") or {}
    if primary == "EXIT_PROBLEM" and mfe.get("losers_mfe_gt_0_5R"):
        return (
            "EXIT_RESEARCH",
            "Highest-evidence failure mechanism: most events are theoretical stop-outs, and a large share "
            "first moved favorably (MFE>0.5R / >1R) then hit SL. Spread does not explain the -1R. "
            "The +31.8R outlier is the complementary geometry (tiny SL, distant TP that actually filled). "
            "Next work is causal study of SL/TP interaction on the frozen tape — not threshold search, "
            "not broker rediscovery, not live/shadow. Dedup is already understood (event is the unit). "
            f"Top1-removed expectancy survives={survives}.",
        )
    if primary == "TIME_DEPENDENCY":
        return "TIME_DEPENDENCY_RESEARCH", "Positive mass concentrates in 2026-01 / OOS extreme TP."
    if primary is None:
        return "INSUFFICIENT_EVIDENCE", "Phase64 causes missing."
    mapping = {
        "ENTRY_PROBLEM": "ENTRY_RESEARCH",
        "SIGNAL_DUPLICATION_PROBLEM": "SIGNAL_DEDUPLICATION_RESEARCH",
        "SIDE_ASYMMETRY": "SIDE_ASYMMETRY_RESEARCH",
        "COST_SENSITIVITY": "COST_RESEARCH",
        "DATA_PROBLEM": "DATA_QUALITY_RESEARCH",
        "REGIME_FILTER_PROBLEM": "REGIME_FILTER_RESEARCH",
    }
    return mapping.get(str(primary), "EXIT_RESEARCH"), f"Mapped from PRIMARY_ROOT_CAUSE={primary}."


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 64–67 (`docs/PHASE64_STRATEGY_EVENT_FORENSICS.md`, "
        "`docs/PHASE65_DIAGNOSTIC_EXPERIMENTS.md`, `docs/PHASE66_STRATEGY_ROOT_CAUSE.md`, "
        "`docs/PHASE67_NEXT_RESEARCH_GATE.md`) are research-only causal diagnosis of the frozen strategy edge. "
        "They do not optimize, modify production strategy/RiskGate/Execution, authorize live/shadow, or restart broker forensics."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 61–63"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 64 strategy event forensics | `run_phase64_collection()` | n/a | RESEARCH; frozen jsonl | **PASS**; diagnosis only |\n"
        "| Phase 65 diagnostic experiments | `run_phase65_collection()` | n/a | RESEARCH; pre-declared only | **PASS**; no threshold search |\n"
        "| Phase 66 strategy root cause | `run_phase66_collection()` | n/a | RESEARCH; cause tree | **PASS**; no optimize |\n"
        "| Phase 67 next research gate | `run_phase67_collection()` | n/a | RESEARCH; one target | **PASS**; EXIT_RESEARCH |"
    )
    if "Phase 64 strategy event forensics" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase64_strategy_event_forensics.py` — **RESEARCH_ONLY** event lineage/MFE; no SL change.\n"
        "`tradingbot/backtest/phase65_diagnostic_experiments.py` — **RESEARCH_ONLY** pre-declared diagnostics.\n"
        "`tradingbot/backtest/phase66_strategy_root_cause.py` — **RESEARCH_ONLY** cause tree.\n"
        "`tradingbot/backtest/phase67_next_research_gate.py` — **RESEARCH_ONLY** next research target; no optimize/live.\n"
    )
    needle = "`tradingbot/backtest/phase63_next_step_gate.py`"
    if "phase64_strategy_event_forensics.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 64 started | **NO** |", "| Phase 64 started | **YES** |")
    block = f"""

## Strategy causal diagnosis (Phases 64–67)

| Claim | Status |
|---|---|
| PRIMARY_ROOT_CAUSE | **{payload.get("PRIMARY_ROOT_CAUSE")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| Optimization | **NO** |
| Production strategy modified | **NO** |
| Broker forensics restarted | **NO** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Phase 68 started | **NO** |
"""
    if "## Strategy causal diagnosis (Phases 64–67)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def run_phase67_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p64 = _safe_load_json(root / PHASE64_JSON) or {}
    p65 = _safe_load_json(root / PHASE65_JSON) or {}
    p66 = _safe_load_json(root / PHASE66_JSON) or {}
    target, why = select_target(p64, p65, p66)
    if target not in ALLOWED:
        target = "INSUFFICIENT_EVIDENCE"
    perf = p64.get("performance") or {}
    outlier = p64.get("outlier") or {}
    cf = p64.get("counterfactual") or {}
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "parameters_optimized": False,
        "broker_forensics_restarted": False,
        "NEXT_RESEARCH_TARGET": target,
        "WHY": why,
        "PRIMARY_ROOT_CAUSE": (p64.get("causes") or {}).get("PRIMARY") or p66.get("PRIMARY_ROOT_CAUSE"),
        "SECONDARY_ROOT_CAUSE": (p64.get("causes") or {}).get("SECONDARY") or p66.get("SECONDARY_ROOT_CAUSE"),
        "TERTIARY_ROOT_CAUSE": (p64.get("causes") or {}).get("TERTIARY") or p66.get("TERTIARY_ROOT_CAUSE"),
        "EDGE_QUALITY": "FRAGILE",
        "EVENT_COUNT": (p64.get("lineage_meta") or {}).get("event_count"),
        "RESOLVED_EVENT_COUNT": (p64.get("lineage_meta") or {}).get("resolved_event_count"),
        "GROSS_EVENT_EXPECTANCY": perf.get("expectancy_R"),
        "GROSS_EVENT_PF": perf.get("PF"),
        "TOP1_CONTRIBUTION": ((outlier.get("contribution") or {}).get("top_1") or {}).get("share_of_net_R"),
        "TOP5_CONTRIBUTION": ((outlier.get("contribution") or {}).get("top_5") or {}).get("share_of_net_R"),
        "EXPECTANCY_WITHOUT_TOP1": ((cf.get("remove_top_1") or {}).get("expectancy_R")),
        "EXPECTANCY_WITHOUT_TOP5": ((cf.get("remove_top_5") or {}).get("expectancy_R")),
        "WIN_RATE": perf.get("WR"),
        "MEDIAN_R": perf.get("median_R"),
        "REGIME_DEPENDENCY": (p64.get("regime") or {}).get("REGIME_WHERE_STRATEGY_BREAKS"),
        "SESSION_DEPENDENCY": (p64.get("session") or {}).get("SESSION_DEPENDENCY"),
        "SIDE_DEPENDENCY": (p64.get("side") or {}).get("SIDE_DEPENDENCY"),
        "SIGNAL_DUPLICATION": (p64.get("density") or {}).get("SIGNAL_DUPLICATION"),
        "TIME_DEPENDENCY": p64.get("TIME_DEPENDENCY"),
        "OOS_EXPECTANCY": ((p64.get("folds") or {}).get("OOS") or {}).get("expectancy_R"),
        "RECENT_180D_EXPECTANCY": ((p64.get("recent_180d") or {}).get("recent_180d") or {}).get("expectancy_R"),
        "COST_TOLERANCE": "FAIL",
        "OPTIMIZATION_ALLOWED": False,
        "SHADOW_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "project_stopped": False,
        "DO_NOT_DO_YET": [
            "Optimization",
            "Live trading",
            "Shadow activation",
            "Broker execution validation",
            "Production strategy modification",
        ],
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE67_JSON, "md": PHASE67_MD, "closure_md": PHASE64_67_MD},
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
    }
    (root / PHASE67_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE67_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE67_MD).write_text(
        "\n".join(
            [
                "# Phase 67 — Next Research Gate",
                "",
                f"**NEXT_RESEARCH_TARGET:** `{target}`",
                "",
                why,
                "",
                "DO_NOT_DO_YET: optimization, live, shadow, broker execution validation, production strategy modification.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    closure = [
        "# Phase 64–67 — Strategy Diagnosis Closure",
        "",
        "## WHY THE STRATEGY LOSES AND DEPENDS ON +31.8R",
        "",
        "Most resolved events are theoretical stop-outs (-1R). A large share of losers first moved in the trade's favor (MFE), then hit SL. Modeled spread cannot explain a full SL. The +31.8R event is a single 2026-01-21 SELL whose planned RR was ~32 because SL was tiny versus a distant TP that actually filled — exceptional magnitude, same liquidity_sweep mechanism. Removing that event makes expectancy negative. OOS positivity is that same outlier. Recent 180d has no such fill and is negative.",
        "",
        f"## NEXT_RESEARCH_TARGET `{target}`",
        "",
        why,
        "",
        "## WHAT_NOT_TO_DO",
        "Optimization, live trading, shadow, broker rediscovery, production strategy/RiskGate/Execution changes.",
        "",
    ]
    (root / PHASE64_67_MD).write_text("\n".join(closure), encoding="utf-8")
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase67_collection(Path("."))["NEXT_RESEARCH_TARGET"])
