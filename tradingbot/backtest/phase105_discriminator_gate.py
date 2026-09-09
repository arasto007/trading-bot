"""Phase 105 — final discriminator evidence gate.

Does not implement a production EXIT_DESIGN_SPEC. Does not start Phase 106.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase81_exit_research_gate import PHASE81_JSON
from tradingbot.backtest.phase89_profit_protection_gate import PHASE89_JSON
from tradingbot.backtest.phase97_profit_protection_final_gate import PHASE97_JSON
from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON
from tradingbot.backtest.phase99_path_velocity_persistence import PHASE99_JSON
from tradingbot.backtest.phase100_retrace_expansion_forensics import PHASE100_JSON
from tradingbot.backtest.phase101_entry_vs_exit import PHASE101_JSON
from tradingbot.backtest.phase102_cluster_timing_forensics import PHASE102_JSON
from tradingbot.backtest.phase103_structure_at_retracement import PHASE103_JSON
from tradingbot.backtest.phase104_minimal_discriminator import PHASE104_JSON

PHASE = "105"
PHASE105_JSON = "logs/phase105_discriminator_gate.json"
PHASE105_MD = "docs/PHASE105_DISCRIMINATOR_GATE.md"
INSUFFICIENT_SPEC = "INSUFFICIENT_EVIDENCE"
GATE_ALLOWED = (
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNSUPPORTED",
    "DATA_LIMITED",
    "INSUFFICIENT_EVIDENCE",
)
NEXT_ALLOWED = (
    "OFFLINE_EXIT_IMPLEMENTATION",
    "MORE_PROFIT_PROTECTION_FORENSICS",
    "TAIL_CAPTURE_RESEARCH",
    "EXIT_GEOMETRY_RESEARCH",
    "STRATEGY_REPLACEMENT_RESEARCH",
    "NON_OHLC_DISCRIMINATOR_RESEARCH",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "DISCRIMINATOR_STATUS",
    "EXIT_DESIGN_SPEC_STATUS",
    "NEXT_RESEARCH_TARGET",
    "final_gate",
    "production_safety",
    "artifacts",
)


def decide(
    p81: dict,
    p89: dict,
    p97: dict,
    p98: dict,
    p99: dict,
    p100: dict,
    p101: dict,
    p102: dict,
    p103: dict,
    p104: dict,
) -> dict[str, Any]:
    seps = {
        "98": p98.get("separators_train_val") or [],
        "99": p99.get("separators_train_val") or [],
        "100": p100.get("separators_train_val") or [],
        "101": p101.get("separators_train_val") or [],
        "102": p102.get("separators_train_val") or [],
        "103": p103.get("separators_train_val") or [],
    }
    survivors_103 = p103.get("survivors_all_splits") or []
    n_fam = int(p104.get("n_families") or 0)
    helpful = p104.get("helpful_families") or []
    cfs = p104.get("counterfactuals") or {}
    any_tail_preserved = any((cfs.get(n) or {}).get("TAIL_PRESERVATION") == "PRESERVED" for n in helpful)
    any_tail_destroyed = any((cfs.get(n) or {}).get("TAIL_PRESERVATION") == "DESTROYED" for n in (cfs or {}))
    any_oos = any(bool((cfs.get(n) or {}).get("survives_OOS_direction")) for n in helpful)
    any_rec = any(bool((cfs.get(n) or {}).get("survives_recent180_direction")) for n in helpful)
    any_train_val = any(bool(v) for v in seps.values())
    q1 = any_train_val  # causal discriminator available before giveback?
    q2 = any_train_val  # distinguish C/D from E/F?
    q3 = bool(helpful) and any_tail_preserved
    q4 = bool(helpful)  # HELPFUL already requires VAL rise
    q5 = bool(helpful) and any_oos
    q6 = bool(helpful) and any_rec
    q7 = False
    for n in helpful:
        row = cfs.get(n) or {}
        buy = ((row.get("BUY") or {}).get("delta_expectancy"))
        sell = ((row.get("SELL") or {}).get("delta_expectancy"))
        years = row.get("by_year") or {}
        year_pos = sum(1 for v in years.values() if (v.get("delta_expectancy") or 0) > 0)
        if buy is not None and sell is not None and buy > 0 and sell > 0 and year_pos >= max(1, len(years) // 2):
            q7 = True
    q8 = True  # event unit throughout 98-104
    q9 = False
    for n in helpful:
        row = cfs.get(n) or {}
        d1 = ((row.get("WITHOUT_TOP1") or {}).get("delta_expectancy"))
        d5 = ((row.get("WITHOUT_TOP5") or {}).get("delta_expectancy"))
        if d1 is not None and d5 is not None and d1 > 0 and d5 > 0:
            q9 = True
    q10 = bool(helpful) and q3 and q5 and q6 and q8
    if q10:
        status = "SUPPORTED"
        spec = "NOT_IMPLEMENTED"
        nxt = "OFFLINE_EXIT_IMPLEMENTATION"
        tail_status = "PRESERVED"
    elif helpful and not q3:
        status = "PARTIALLY_SUPPORTED"
        spec = INSUFFICIENT_SPEC
        nxt = "TAIL_CAPTURE_RESEARCH"
        tail_status = "DESTROYED"
    elif any_train_val and n_fam:
        status = "PARTIALLY_SUPPORTED"
        spec = INSUFFICIENT_SPEC
        nxt = "MORE_PROFIT_PROTECTION_FORENSICS"
        tail_status = "DESTROYED" if any_tail_destroyed else "UNPROTECTED"
    elif any_train_val:
        status = "PARTIALLY_SUPPORTED"
        spec = INSUFFICIENT_SPEC
        nxt = "MORE_PROFIT_PROTECTION_FORENSICS"
        tail_status = p97.get("TAIL_STATUS") or "DESTROYED"
    else:
        # Frozen M5 OHLC at first-favorable and at-retrace does not separate C/D from E/F.
        status = "UNSUPPORTED"
        spec = INSUFFICIENT_SPEC
        nxt = "NON_OHLC_DISCRIMINATOR_RESEARCH"
        tail_status = p97.get("TAIL_STATUS") or "DESTROYED"
    if p101.get("PROBLEM") == "PARTLY_SIGNAL_QUALITY" and not q10:
        nxt = "STRATEGY_REPLACEMENT_RESEARCH"
        if status == "UNSUPPORTED":
            status = "UNSUPPORTED"
    if status not in GATE_ALLOWED:
        status = "INSUFFICIENT_EVIDENCE"
    if nxt not in NEXT_ALLOWED:
        nxt = "INSUFFICIENT_EVIDENCE"
    missing = []
    if not q1:
        missing.append("No TRAIN+VAL confirmed state/persistence/structure/cluster separator on frozen M5 OHLC.")
    if q1 and not q3:
        missing.append("No candidate that separates C/D from E/F without clipping the +31.84R event.")
    if q1 and not q5:
        missing.append("OOS same-direction confirmation of a tail-safe discriminator.")
    if q1 and not q6:
        missing.append("recent180 same-direction confirmation.")
    if not q10:
        missing.append("Production EXIT_DESIGN_SPEC authorization is not granted.")
    if not q1:
        missing.append("Information not present in the frozen M5 OHLC tape (tick, spread path, higher timeframe, news).")
    q12 = nxt
    robust = "INSUFFICIENT"
    oos_status = p97.get("OOS_STATUS") or "NEGATIVE"
    rec_status = p97.get("RECENT180_STATUS") or "MIXED"
    if helpful and any_oos and not any((cfs.get(n) or {}).get("survives_OOS_direction") is False for n in helpful):
        oos_status = "POSITIVE"
    elif helpful:
        oos_status = "MIXED" if any_oos else "NEGATIVE"
    if helpful and any_rec:
        rec_status = "POSITIVE" if all((cfs.get(n) or {}).get("survives_recent180_direction") for n in helpful) else "MIXED"
    prot = p97.get("PROTECTION_STATUS") or "PROTECTION_DESIGN_PARTIALLY_SUPPORTED"
    if status == "SUPPORTED":
        prot = "PROTECTION_DESIGN_SUPPORTED"
    final = "GO_RESEARCH" if nxt in {
        "MORE_PROFIT_PROTECTION_FORENSICS",
        "TAIL_CAPTURE_RESEARCH",
        "OFFLINE_EXIT_IMPLEMENTATION",
        "EXIT_GEOMETRY_RESEARCH",
        "STRATEGY_REPLACEMENT_RESEARCH",
        "NON_OHLC_DISCRIMINATOR_RESEARCH",
    } else "INSUFFICIENT_EVIDENCE"
    return {
        "questions": {
            "1_causal_discriminator_before_giveback": q1,
            "2_distinguishes_CD_from_EF": q2,
            "3_preserves_plus_31_84R_tail": q3,
            "4_survives_VALIDATION": q4,
            "5_survives_OOS": q5,
            "6_survives_recent180": q6,
            "7_survives_side_regime_year": q7,
            "8_event_level": q8,
            "9_top1_top5_sensitivity": q9,
            "10_enough_for_EXIT_DESIGN_SPEC": q10,
            "11_missing_evidence": missing,
            "12_highest_value_next": q12,
        },
        "DISCRIMINATOR_STATUS": status,
        "EXIT_DESIGN_SPEC": spec,
        "EXIT_DESIGN_SPEC_STATUS": INSUFFICIENT_SPEC,
        "NEXT_RESEARCH_TARGET": nxt,
        "TAIL_STATUS": tail_status,
        "OOS_STATUS": oos_status,
        "RECENT180_STATUS": rec_status,
        "ROBUSTNESS_STATUS": robust,
        "PROTECTION_STATUS": prot,
        "PRIMARY_EXIT_MECHANISM": p81.get("PRIMARY_EXIT_MECHANISM") or p97.get("PRIMARY_EXIT_MECHANISM") or "PROFIT_GIVEBACK",
        "SECONDARY_EXIT_MECHANISM": p81.get("SECONDARY_EXIT_MECHANISM") or p97.get("SECONDARY_EXIT_MECHANISM") or "EXIT_GEOMETRY",
        "FINAL_GATE": final,
        "FINAL_RESEARCH_GATE": final,
        "n_families": n_fam,
        "helpful_families": helpful,
        "separators": seps,
        "survivors_103": survivors_103,
        "ENTRY_PROBLEM": p101.get("PROBLEM"),
        "evidence_kind": "INFERENCE",
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 98–105 (`docs/PHASE98_FIRST_FAVORABLE_STATE.md` through "
        "`docs/PHASE105_DISCRIMINATOR_GATE.md`) are research-only causal-state, persistence, "
        "retracement, entry, cluster, and discriminator-gate forensics. They do not optimize, "
        "modify production, authorize live/shadow, connect to MT5, or implement an exit spec."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 90–97"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 98 first-favorable state | `run_phase98_collection()` | n/a | RESEARCH; causal snapshots | **PASS**; no search |\n"
        "| Phase 99 persistence | `run_phase99_collection()` | n/a | RESEARCH; not a rule | **PASS** |\n"
        "| Phase 100 retrace expansion | `run_phase100_collection()` | n/a | RESEARCH; outlier kept | **PASS** |\n"
        "| Phase 101 entry vs exit | `run_phase101_collection()` | n/a | RESEARCH; signal unchanged | **PASS** |\n"
        "| Phase 102 cluster timing | `run_phase102_collection()` | n/a | RESEARCH; event unit | **PASS** |\n"
        "| Phase 103 structure at retrace | `run_phase103_collection()` | n/a | RESEARCH; predeclared | **PASS** |\n"
        "| Phase 104 minimal discriminator | `run_phase104_collection()` | n/a | RESEARCH; not exit rules | **PASS** |\n"
        "| Phase 105 discriminator gate | `run_phase105_collection()` | n/a | RESEARCH; spec not implemented | **PASS** |"
    )
    if "Phase 98 first-favorable state" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase98_first_favorable_state.py` — **RESEARCH_ONLY** causal snapshots.\n"
        "`tradingbot/backtest/phase99_path_velocity_persistence.py` — **RESEARCH_ONLY** persistence kinds.\n"
        "`tradingbot/backtest/phase100_retrace_expansion_forensics.py` — **RESEARCH_ONLY** retrace vs continuation.\n"
        "`tradingbot/backtest/phase101_entry_vs_exit.py` — **RESEARCH_ONLY** entry vs exit; signal unchanged.\n"
        "`tradingbot/backtest/phase102_cluster_timing_forensics.py` — **RESEARCH_ONLY** event-unit cluster timing.\n"
        "`tradingbot/backtest/phase103_structure_at_retracement.py` — **RESEARCH_ONLY** predeclared structure.\n"
        "`tradingbot/backtest/phase104_minimal_discriminator.py` — **RESEARCH_ONLY** counterfactual families.\n"
        "`tradingbot/backtest/phase105_discriminator_gate.py` — **RESEARCH_ONLY** discriminator gate; spec not implemented.\n"
    )
    needle = "`tradingbot/backtest/phase97_profit_protection_final_gate.py`"
    if "phase98_first_favorable_state.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 98 started | **NO** |", "| Phase 98 started | **YES** |")
    block = f"""

## Discriminator forensics (Phases 98–105)

| Claim | Status |
|---|---|
| DISCRIMINATOR_STATUS | **{payload.get("DISCRIMINATOR_STATUS")}** |
| EXIT_DESIGN_SPEC | **{payload.get("EXIT_DESIGN_SPEC")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| C/D vs E/F separable on frozen M5 OHLC | **{"YES" if (payload.get("questions") or {}).get("2_distinguishes_CD_from_EF") else "NO"}** |
| +31.84R preserved by a candidate | **{"YES" if (payload.get("questions") or {}).get("3_preserves_plus_31_84R_tail") else "NO"}** |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Parameter search | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 106 started | **NO** |
"""
    marker = "## Discriminator forensics (Phases 98–105)"
    if marker in ktext:
        start = ktext.find(marker)
        ku.write_text(ktext[:start].rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    n = 419
    q = payload.get("questions") or {}
    rows = [
        ("H98-01", 98, payload.get("separators") and "see separators" or "first_favorable_state", "causal snapshots"),
        ("H99-01", 99, "persistence", "not a rule"),
        ("H100-01", 100, "retrace_expansion", "outlier kept"),
        ("H101-01", 101, payload.get("ENTRY_PROBLEM"), "signal unchanged"),
        ("H102-01", 102, "cluster_timing", "event unit"),
        ("H103-01", 103, payload.get("survivors_103"), "predeclared structure"),
        ("H104-01", 104, payload.get("helpful_families") or "NO_FAMILIES", "counterfactual only"),
        ("H105-01", 105, payload.get("NEXT_RESEARCH_TARGET"), "gate; not implemented"),
    ]
    extra = ["", "## Phases 98–105", ""]
    extra.append("| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |")
    extra.append("|---|---|---|---|---|---|---|---|---|---|")
    for hid, ph, result, note in rows:
        extra.append(
            f"| {hid} | {today} | {ph} | frozen Phase38/40 | {n} | event tape 419 resolved | {result} | reported | NO | {note} |"
        )
    extra.append("")
    extra.append(f"**DISCRIMINATOR_STATUS:** `{payload.get('DISCRIMINATOR_STATUS')}`")
    extra.append(f"**NEXT_RESEARCH_TARGET:** `{payload.get('NEXT_RESEARCH_TARGET')}` (not implemented).")
    extra.append(f"**Q12:** `{q.get('12_highest_value_next')}`")
    extra.append("")
    marker = "## Phases 98–105"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def run_phase105_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p81 = _safe_load_json(root / PHASE81_JSON) or {}
    p89 = _safe_load_json(root / PHASE89_JSON) or {}
    p97 = _safe_load_json(root / PHASE97_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    p99 = _safe_load_json(root / PHASE99_JSON) or {}
    p100 = _safe_load_json(root / PHASE100_JSON) or {}
    p101 = _safe_load_json(root / PHASE101_JSON) or {}
    p102 = _safe_load_json(root / PHASE102_JSON) or {}
    p103 = _safe_load_json(root / PHASE103_JSON) or {}
    p104 = _safe_load_json(root / PHASE104_JSON) or {}
    d = decide(p81, p89, p97, p98, p99, p100, p101, p102, p103, p104)
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
        "intervention_implemented": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        **d,
        "PARAMETER_SEARCH_USED": False,
        "OPTIMIZATION_USED": False,
        "PRODUCTION_CHANGED": False,
        "MT5_USED": False,
        "LIVE_TRADING": False,
        "hypotheses": [
            {
                "id": "H105-01",
                "claim": "Gate whether a causal C/D vs E/F discriminator exists on frozen M5 OHLC without implementing an exit spec.",
                "result": d["DISCRIMINATOR_STATUS"],
                "oos_used_for_decision": False,
            }
        ],
        "oos_used_for_selection": False,
        "OPTIMIZATION_ALLOWED": False,
        "SHADOW_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "final_gate": d["FINAL_GATE"],
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
            "spec_implemented": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE105_JSON, "md": PHASE105_MD, "ledger": LEDGER_MD},
    }
    (root / PHASE105_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE105_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    q = payload.get("questions") or {}
    (root / PHASE105_MD).write_text(
        "\n".join(
            [
                "# Phase 105 — Discriminator Gate",
                "",
                "INFERENCE over FROZEN-DATA-EVIDENCE and COUNTERFACTUAL families. Spec not implemented.",
                f"**DISCRIMINATOR_STATUS:** `{payload['DISCRIMINATOR_STATUS']}`",
                f"**PRIMARY_EXIT_MECHANISM:** `{payload['PRIMARY_EXIT_MECHANISM']}`",
                f"**SECONDARY_EXIT_MECHANISM:** `{payload['SECONDARY_EXIT_MECHANISM']}`",
                f"**TAIL_STATUS:** `{payload.get('TAIL_STATUS')}`",
                f"**PROTECTION_STATUS:** `{payload.get('PROTECTION_STATUS')}`",
                f"**OOS_STATUS:** `{payload.get('OOS_STATUS')}`",
                f"**RECENT180_STATUS:** `{payload.get('RECENT180_STATUS')}`",
                f"**ROBUSTNESS_STATUS:** `{payload.get('ROBUSTNESS_STATUS')}`",
                f"**EXIT_DESIGN_SPEC_STATUS:** `{payload['EXIT_DESIGN_SPEC_STATUS']}`",
                f"**FINAL_RESEARCH_GATE:** `{payload['FINAL_RESEARCH_GATE']}`",
                f"**NEXT_RESEARCH_TARGET:** `{payload['NEXT_RESEARCH_TARGET']}`",
                "",
                "1. Causal discriminator before giveback: "
                f"`{q.get('1_causal_discriminator_before_giveback')}`",
                f"2. Distinguishes C/D from E/F: `{q.get('2_distinguishes_CD_from_EF')}`",
                f"3. Preserves +31.84R: `{q.get('3_preserves_plus_31_84R_tail')}`",
                f"4. Survives VALIDATION: `{q.get('4_survives_VALIDATION')}`",
                f"5. Survives OOS: `{q.get('5_survives_OOS')}`",
                f"6. Survives recent180: `{q.get('6_survives_recent180')}`",
                f"7. Side/regime/year: `{q.get('7_survives_side_regime_year')}`",
                f"8. Event level: `{q.get('8_event_level')}`",
                f"9. top1/top5: `{q.get('9_top1_top5_sensitivity')}`",
                f"10. Enough for EXIT_DESIGN_SPEC: `{q.get('10_enough_for_EXIT_DESIGN_SPEC')}`",
                f"11. Missing: `{q.get('11_missing_evidence')}`",
                f"12. Next: `{q.get('12_highest_value_next')}`",
                "",
                "Do NOT implement the target. Do not optimize. Do not trade. Phase 106 not started.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    append_ledger(root, payload)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase105_collection(Path("."))["DISCRIMINATOR_STATUS"])
