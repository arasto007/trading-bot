"""Phase 73 — exit research gate.

Chooses exactly one next research target and writes a precise spec.
Does NOT implement the intervention.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    UNKNOWN,
    _git_head,
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import PHASE68_JSON
from tradingbot.backtest.phase69_exit_geometry import PHASE69_JSON
from tradingbot.backtest.phase70_exit_counterfactuals import PHASE70_JSON
from tradingbot.backtest.phase71_extreme_winner_forensics import PHASE71_JSON
from tradingbot.backtest.phase72_exit_root_cause import PHASE72_JSON

PHASE = "73"
PHASE73_JSON = "logs/phase73_exit_research_gate.json"
PHASE73_MD = "docs/PHASE73_EXIT_RESEARCH_GATE.md"
LEDGER_MD = "docs/RESEARCH_LEDGER.md"
BLOCKED = "BLOCKED"
ALLOWED = (
    "EXIT_GEOMETRY_RESEARCH",
    "STOP_PLACEMENT_RESEARCH",
    "PROFIT_PROTECTION_RESEARCH",
    "TP_TARGET_RESEARCH",
    "TIME_EXIT_RESEARCH",
    "REGIME_CONDITIONAL_EXIT_RESEARCH",
    "SIDE_CONDITIONAL_EXIT_RESEARCH",
    "ENTRY_BEFORE_EXIT_RESEARCH",
    "SIGNAL_DEDUPLICATION_BEFORE_EXIT",
    "EXTREME_WINNER_INVESTIGATION",
    "DATA_QUALITY_INVESTIGATION",
    "STRATEGY_REPLACEMENT",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "NEXT_RESEARCH_TARGET",
    "spec",
    "final_gate",
    "production_safety",
    "artifacts",
)


def select_target(p68: dict[str, Any], p72: dict[str, Any]) -> tuple[str, str]:
    primary = p72.get("PRIMARY_CAUSE")
    n05 = int(p68.get("LOSS_AFTER_0_5R") or 0)
    n1 = int(p68.get("LOSS_AFTER_1R") or 0)
    n_loss = int((p68.get("lineage_meta") or {}).get("LOSS_SL") or 0)
    mech = (p68.get("mechanism_ranking") or {}).get("PRIMARY_MECHANISM")
    # Selection uses FULL-tape / TRAIN-visible giveback evidence. OOS is not a selector.
    if primary == "PROFIT_GIVEBACK" and n05 >= 100 and n1 >= 50:
        return (
            "PROFIT_PROTECTION_RESEARCH",
            (
                f"FULL-tape LOSS_SL={n_loss}: LOSS_AFTER_0.5R={n05}, LOSS_AFTER_1R={n1}, "
                f"mechanism={mech}, PRIMARY_CAUSE={primary}. "
                "The failure is give-back after meaningful MFE with no protective exit. "
                "Next work is one predeclared protection family, not SL/TP grid search."
            ),
        )
    if primary == "STOP_TOO_CLOSE":
        return "STOP_PLACEMENT_RESEARCH", "Immediate losers dominate; inspect stop placement next."
    if primary == "EXIT_GEOMETRY":
        return "EXIT_GEOMETRY_RESEARCH", "Hybrid unbounded RR is the leading cause without give-back majority."
    if primary == "DATA_OR_LABELING_ARTIFACT":
        return "DATA_QUALITY_INVESTIGATION", "Path/label integrity failed."
    return "INSUFFICIENT_EVIDENCE", f"PRIMARY_CAUSE={primary} did not map to a single gate."


def build_spec(target: str, p68: dict[str, Any], p72: dict[str, Any]) -> dict[str, Any]:
    return {
        "NEXT_RESEARCH_TARGET": target,
        "hypothesis_id": "H74-01",
        "hypothesis": (
            "On the frozen event tape, a single predeclared protective-exit family "
            "(descriptive path classification: if MFE first reaches +1.0R, treat subsequent SL as a "
            "give-back failure that a breakeven-after-+1R rule would have converted) "
            "will raise TRAIN event expectancy and keep VAL confirmatory without using OOS to choose the rule."
        ),
        "why": (
            "Phases 68-72 show the typical loser reaches meaningful MFE then hits -1R. "
            "ENABLE_PARTIAL_TP is false. This tests WHETHER protection of that type addresses the "
            "observed failure, not WHICH threshold is optimal."
        ),
        "existing_data": [
            "logs/phase40_raw_setups.jsonl",
            "data/XAUUSD_i_5m_phase38.parquet",
            "logs/phase68_exit_forensics.json compact_events / path metrics",
        ],
        "frozen": [
            "Phase40 jsonl and parquet fingerprint",
            "Strategy / RiskGate / Execution / PA lock / calibration / live config",
            "Historical Phase40-72 artifacts",
            "Official baseline including +31.84R",
        ],
        "single_intervention_family": (
            "BREAKEVEN_AFTER_PREDECLARED_PLUS_1R — one family, threshold frozen at +1.0R "
            "from the predeclared MFE diagnostic, not searched."
        ),
        "variants_allowed": 1,
        "success": (
            "TRAIN expectancy increases vs frozen event baseline AND VALIDATION expectancy does not reverse sign "
            "relative to its own frozen baseline AND top1-removed TRAIN expectancy is not worse than frozen top1-removed TRAIN. "
            "Gross vs modeled-cost reported separately. No profitability claim."
        ),
        "failure": (
            "VAL does not confirm TRAIN, OR the family only 'works' when the +31.84R event is required, "
            "OR implementation would need extra variants/thresholds."
        ),
        "train_val_oos": {
            "TRAIN": "bar-index 0-150000 — may fit the single predeclared family (no search)",
            "VALIDATION": "150000-200000 — confirm or reject",
            "OOS": "200000-250000 — FROZEN until after VAL decision; not used to select",
            "recent_180d": "report only; never tune",
        },
        "untouched_period_protection": "Do not peek at OOS to accept/reject the family. Record OOS only after VAL lock.",
        "multiple_testing": {
            "families": 1,
            "thresholds_searched": 0,
            "bonferroni_N": 1,
            "optional_second_look": "FORBIDDEN in the next phase",
        },
        "event_vs_signal": "Event-level primary; signal-level reported as inflated.",
        "gross_vs_modeled_cost": "Gross theoretical first; modeled 1x cost is diagnostic only.",
        "do_not_implement_in_phase73": True,
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 68–73 (`docs/PHASE68_EXIT_FORENSICS.md`, `docs/PHASE69_EXIT_GEOMETRY.md`, "
        "`docs/PHASE70_EXIT_COUNTERFACTUALS.md`, `docs/PHASE71_EXTREME_WINNER.md`, "
        "`docs/PHASE72_EXIT_ROOT_CAUSE.md`, `docs/PHASE73_EXIT_RESEARCH_GATE.md`) are research-only "
        "exit forensics on the frozen tape. They do not optimize, modify production strategy/RiskGate/"
        "Execution, authorize live/shadow, connect to MT5, or restart broker forensics."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 64–67"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 68 exit forensics | `run_phase68_collection()` | n/a | RESEARCH; frozen path walk | **PASS**; diagnosis only |\n"
        "| Phase 69 exit geometry | `run_phase69_collection()` | n/a | RESEARCH; code inspection | **PASS**; no SL/TP change |\n"
        "| Phase 70 exit counterfactuals | `run_phase70_collection()` | n/a | RESEARCH; predeclared only | **PASS**; no search |\n"
        "| Phase 71 extreme winner | `run_phase71_collection()` | n/a | RESEARCH; outlier kept | **PASS**; baseline unchanged |\n"
        "| Phase 72 exit root cause | `run_phase72_collection()` | n/a | RESEARCH; re-ranked causes | **PASS**; no optimize |\n"
        "| Phase 73 exit research gate | `run_phase73_collection()` | n/a | RESEARCH; one target spec | **PASS**; not implemented |"
    )
    if "Phase 68 exit forensics" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase68_exit_forensics.py` — **RESEARCH_ONLY** ENTRY-EXIT path walk; no SL change.\n"
        "`tradingbot/backtest/phase69_exit_geometry.py` — **RESEARCH_ONLY** SL/TP code inspection.\n"
        "`tradingbot/backtest/phase70_exit_counterfactuals.py` — **RESEARCH_ONLY** predeclared diagnostics.\n"
        "`tradingbot/backtest/phase71_extreme_winner_forensics.py` — **RESEARCH_ONLY** outlier forensics.\n"
        "`tradingbot/backtest/phase72_exit_root_cause.py` — **RESEARCH_ONLY** cause matrix.\n"
        "`tradingbot/backtest/phase73_exit_research_gate.py` — **RESEARCH_ONLY** next-target spec; not implemented.\n"
    )
    needle = "`tradingbot/backtest/phase67_next_research_gate.py`"
    if "phase68_exit_forensics.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 68 started | **NO** |", "| Phase 68 started | **YES** |")
    block = f"""

## Exit forensics (Phases 68–73)

| Claim | Status |
|---|---|
| PRIMARY_CAUSE | **{payload.get("PRIMARY_CAUSE")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| EXTREME_WINNER_CLASSIFICATION | **{payload.get("EXTREME_WINNER_CLASSIFICATION")}** |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Phase 74 started | **NO** |
"""
    if "## Exit forensics (Phases 68–73)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def write_ledger(root: Path, payload: dict[str, Any], collected: list[dict[str, Any]]) -> None:
    lines = [
        "# Research Ledger",
        "",
        "Event-level frozen tape: `logs/phase40_raw_setups.jsonl` + `data/XAUUSD_i_5m_phase38.parquet`.",
        "Baseline: Phase 40–67 unchanged. Official expectancy includes the +31.84R event.",
        "OOS is reported in diagnostics and is **not** used to select hypotheses or the Phase 73 target.",
        "",
        "| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    today = datetime.now(timezone.utc).date().isoformat()
    for row in collected:
        lines.append(
            f"| {row['id']} | {today} | {row['phase']} | frozen Phase38/40 | {row.get('n', UNKNOWN)} | "
            f"event tape 419 resolved | {row.get('result')} | {row.get('oos_touched')} | "
            f"{row.get('oos_decision')} | {row.get('next')} |"
        )
    lines.extend(
        [
            "",
            f"**HYPOTHESES_TESTED:** {payload.get('HYPOTHESES_TESTED')}",
            f"**DIAGNOSTICS_RUN:** {payload.get('DIAGNOSTICS_RUN')}",
            f"**NEXT_RESEARCH_TARGET:** `{payload.get('NEXT_RESEARCH_TARGET')}` (not implemented).",
            "",
        ]
    )
    (root / LEDGER_MD).write_text("\n".join(lines), encoding="utf-8")


def run_phase73_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p68 = _safe_load_json(root / PHASE68_JSON) or {}
    p69 = _safe_load_json(root / PHASE69_JSON) or {}
    p70 = _safe_load_json(root / PHASE70_JSON) or {}
    p71 = _safe_load_json(root / PHASE71_JSON) or {}
    p72 = _safe_load_json(root / PHASE72_JSON) or {}
    target, why = select_target(p68, p72)
    if target not in ALLOWED:
        target = "INSUFFICIENT_EVIDENCE"
    spec = build_spec(target, p68, p72)
    hyps = []
    for blob in (p68, p69, p70, p71, p72):
        hyps.extend(blob.get("hypotheses") or [])
    hyps.append(
        {
            "id": "H73-01",
            "claim": "Select exactly one next research target from 68-72 without using OOS as the selector.",
            "result": target,
            "oos_used_for_decision": False,
        }
    )
    diag_count = 0
    for blob in (p68, p69, p70, p71, p72):
        d = blob.get("diagnostics_run") or []
        diag_count += len(d)
    tests_count = sum(int(b.get("tests_performed") or 0) for b in (p68, p69, p70, p71, p72)) + 1
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "mt5_launched": False,
        "env_accessed": False,
        "intervention_implemented": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "NEXT_RESEARCH_TARGET": target,
        "WHY": why,
        "spec": spec,
        "PRIMARY_CAUSE": p72.get("PRIMARY_CAUSE"),
        "SECONDARY_CAUSE": p72.get("SECONDARY_CAUSE"),
        "TERTIARY_CAUSE": p72.get("TERTIARY_CAUSE"),
        "EXIT_FAILURE_RATE": p68.get("EXIT_FAILURE_RATE"),
        "LOSS_AFTER_0_5R": p68.get("LOSS_AFTER_0_5R"),
        "LOSS_AFTER_1R": p68.get("LOSS_AFTER_1R"),
        "MEDIAN_TIME_TO_REVERSAL": p68.get("MEDIAN_TIME_TO_REVERSAL"),
        "TOP1_REMOVAL_EXPECTANCY": p68.get("TOP1_REMOVAL_EXPECTANCY") or p71.get("TOP1_REMOVAL_EXPECTANCY"),
        "TOP5_REMOVAL_EXPECTANCY": p68.get("TOP5_REMOVAL_EXPECTANCY") or p71.get("TOP5_REMOVAL_EXPECTANCY"),
        "EXTREME_WINNER_CLASSIFICATION": p69.get("EXTREME_WINNER_CLASSIFICATION") or p71.get("EXTREME_WINNER_CLASSIFICATION"),
        "HYPOTHESES_TESTED": len(hyps),
        "DIAGNOSTICS_RUN": diag_count,
        "tests_performed_total": tests_count,
        "hypotheses": hyps,
        "oos_used_for_selection": False,
        "recent_180d_used_for_tuning": False,
        "OPTIMIZATION_ALLOWED": False,
        "SHADOW_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "PRODUCTION_CHANGED": False,
        "MT5_USED": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "PA_LOCK": "NOT_MODIFIED",
            "CALIBRATION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
            "spec_implemented": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE73_JSON, "md": PHASE73_MD, "ledger": LEDGER_MD},
    }
    (root / PHASE73_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE73_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE73_MD).write_text(
        "\n".join(
            [
                "# Phase 73 — Exit Research Gate",
                "",
                f"**NEXT_RESEARCH_TARGET:** `{target}`",
                "",
                why,
                "",
                "## Spec (not implemented)",
                "",
                f"- Hypothesis `{spec['hypothesis_id']}`: {spec['hypothesis']}",
                f"- Single intervention family: {spec['single_intervention_family']}",
                f"- Variants allowed: {spec['variants_allowed']}",
                f"- Success: {spec['success']}",
                f"- Failure: {spec['failure']}",
                f"- TRAIN/VAL/OOS: {spec['train_val_oos']}",
                f"- Multiple testing: {spec['multiple_testing']}",
                "",
                "DO_NOT_IMPLEMENT in this phase. No optimization, live, shadow, MT5, or production change.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    n_res = (p68.get("lineage_meta") or {}).get("resolved_event_count")
    collected = [
        {"id": "H68-01", "phase": 68, "n": n_res, "result": "majority LOSS_SL first favorable", "oos_touched": "reported", "oos_decision": "NO", "next": "69"},
        {"id": "H68-02", "phase": 68, "n": n_res, "result": (p68.get("mechanism_ranking") or {}).get("PRIMARY_MECHANISM"), "oos_touched": "reported", "oos_decision": "NO", "next": "69"},
        {"id": "H69-01", "phase": 69, "n": n_res, "result": "same SL/TP path", "oos_touched": "NO", "oos_decision": "NO", "next": "70"},
        {"id": "H69-02", "phase": 69, "n": n_res, "result": payload.get("EXTREME_WINNER_CLASSIFICATION"), "oos_touched": "NO", "oos_decision": "NO", "next": "70"},
        {"id": "H70-A", "phase": 70, "n": n_res, "result": "LOSS_AFTER_0.5R descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-B", "phase": 70, "n": n_res, "result": "breakeven-reach descriptive; SL not moved", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-C", "phase": 70, "n": n_res, "result": "capture ratio descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-D", "phase": 70, "n": n_res, "result": "time-to-reversal descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-E", "phase": 70, "n": n_res, "result": "hold-window descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-F", "phase": 70, "n": n_res, "result": "regime exit descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-G", "phase": 70, "n": n_res, "result": "session exit descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-H", "phase": 70, "n": n_res, "result": "side exit descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H70-I", "phase": 70, "n": n_res, "result": "volatility labels descriptive", "oos_touched": "reported", "oos_decision": "NO", "next": "71"},
        {"id": "H71-01", "phase": 71, "n": n_res, "result": payload.get("EXTREME_WINNER_CLASSIFICATION"), "oos_touched": "reported", "oos_decision": "NO", "next": "72"},
        {"id": "H72-01", "phase": 72, "n": n_res, "result": payload.get("PRIMARY_CAUSE"), "oos_touched": "reported", "oos_decision": "NO", "next": "73"},
        {"id": "H73-01", "phase": 73, "n": n_res, "result": target, "oos_touched": "reported", "oos_decision": "NO", "next": "spec only; not implemented"},
    ]
    write_ledger(root, payload, collected)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase73_collection(Path("."))["NEXT_RESEARCH_TARGET"])
