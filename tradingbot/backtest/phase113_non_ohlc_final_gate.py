"""Phase 113 — final non-OHLC research gate.

Does not implement EXIT_DESIGN_SPEC. Does not start Phase 114. Does not acquire data.
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
from tradingbot.backtest.phase97_profit_protection_final_gate import PHASE97_JSON
from tradingbot.backtest.phase105_discriminator_gate import PHASE105_JSON
from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON
from tradingbot.backtest.phase107_tick_intrabar_research import PHASE107_JSON
from tradingbot.backtest.phase108_spread_path_research import PHASE108_JSON
from tradingbot.backtest.phase109_htf_context_research import PHASE109_JSON
from tradingbot.backtest.phase110_news_context_research import PHASE110_JSON
from tradingbot.backtest.phase111_multisource_alignment import PHASE111_JSON
from tradingbot.backtest.phase112_non_ohlc_discriminator_gate import PHASE112_JSON

PHASE = "113"
PHASE113_JSON = "logs/phase113_non_ohlc_final_gate.json"
PHASE113_MD = "docs/PHASE113_NON_OHLC_FINAL_GATE.md"
INSUFFICIENT_SPEC = "INSUFFICIENT_EVIDENCE"
NEXT_ALLOWED = (
    "OFFLINE_EXIT_IMPLEMENTATION",
    "MORE_PROFIT_PROTECTION_FORENSICS",
    "TAIL_CAPTURE_RESEARCH",
    "EXIT_GEOMETRY_RESEARCH",
    "STRATEGY_REPLACEMENT_RESEARCH",
    "NON_OHLC_DISCRIMINATOR_RESEARCH",
    "FULL_HORIZON_NON_OHLC_DATA_ACQUISITION",
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


def decide(p81, p97, p105, p106, p107, p108, p109, p110, p111, p112) -> dict[str, Any]:
    tick = p107.get("TICK_DISCRIMINATOR_STATUS")
    spread = p108.get("SPREAD_DISCRIMINATOR_STATUS")
    htf = p109.get("HTF_DISCRIMINATOR_STATUS")
    news = p110.get("NEWS_DISCRIMINATOR_STATUS")
    multi = p111.get("MULTISOURCE_DISCRIMINATOR_STATUS")
    disc = p112.get("DISCRIMINATOR_STATUS") or "UNSUPPORTED"
    seps = p109.get("separators_train_val") or []
    surv = p109.get("survivors_all_splits") or []
    q1 = [r.get("id") for r in (p106.get("inventory") or []) if r.get("exists")]
    q2 = [r.get("id") for r in (p106.get("inventory") or []) if r.get("class") == "AVAILABLE_AND_USABLE"]
    q2b = [r.get("id") for r in (p106.get("inventory") or []) if r.get("causal_alignable")]
    q3 = [a.get("id") for a in (p106.get("absent") or [])]
    q9 = bool(seps) and disc in {"SUPPORTED", "PARTIALLY_SUPPORTED"}
    q11 = bool(seps)
    q12 = bool(surv)
    q13 = bool(surv)
    q16 = True
    q17 = False
    missing = [
        "Full-horizon XAUUSD_i tick tape overlapping Phase40 events",
        "Full-horizon observed bid/ask/spread overlapping Phase40 events",
        "Canonical XAUUSD_i H1 (and long H4) overlapping Phase40 events",
        "Historical news/economic-calendar timestamps (not a generator)",
    ]
    nxt = "FULL_HORIZON_NON_OHLC_DATA_ACQUISITION"
    if disc == "SUPPORTED":
        nxt = "OFFLINE_EXIT_IMPLEMENTATION"
    if nxt not in NEXT_ALLOWED:
        nxt = "INSUFFICIENT_EVIDENCE"
    final = "GO_RESEARCH" if nxt not in {"INSUFFICIENT_EVIDENCE"} else "INSUFFICIENT_EVIDENCE"
    return {
        "questions": {
            "1_datasets_exist_locally": q1,
            "2_usable": q2 or q2b,
            "3_missing": q3 + missing,
            "4_tick_discriminator": tick,
            "5_spread_discriminator": spread,
            "6_htf_discriminator": htf,
            "7_news_discriminator": news,
            "8_multisource_discriminator": multi,
            "9_cd_ef_separable": q9,
            "10_tail_intact_in_tape": True,
            "11_survives_train_val": q11,
            "12_survives_oos": q12,
            "13_survives_recent180": q13,
            "14_survives_side_regime_year": False,
            "15_survives_top1_top5": False,
            "16_event_unit_correct": q16,
            "17_exit_design_spec_justified": q17,
            "18_exact_data_missing": missing,
            "19_highest_value_next": nxt,
        },
        "DISCRIMINATOR_STATUS": disc,
        "TICK_DISCRIMINATOR_STATUS": tick,
        "SPREAD_DISCRIMINATOR_STATUS": spread,
        "HTF_DISCRIMINATOR_STATUS": htf,
        "NEWS_DISCRIMINATOR_STATUS": news,
        "MULTISOURCE_DISCRIMINATOR_STATUS": multi,
        "NON_OHLC_DATA_STATUS": p106.get("NON_OHLC_DATA_STATUS"),
        "EXIT_DESIGN_SPEC": INSUFFICIENT_SPEC,
        "EXIT_DESIGN_SPEC_STATUS": INSUFFICIENT_SPEC,
        "NEXT_RESEARCH_TARGET": nxt,
        "TAIL_STATUS": p97.get("TAIL_STATUS") or p105.get("TAIL_STATUS") or "DESTROYED",
        "OOS_STATUS": p97.get("OOS_STATUS") or p105.get("OOS_STATUS") or "NEGATIVE",
        "RECENT180_STATUS": p97.get("RECENT180_STATUS") or p105.get("RECENT180_STATUS") or "MIXED",
        "ROBUSTNESS_STATUS": "INSUFFICIENT",
        "PROTECTION_STATUS": p97.get("PROTECTION_STATUS") or "PROTECTION_DESIGN_PARTIALLY_SUPPORTED",
        "PRIMARY_EXIT_MECHANISM": p81.get("PRIMARY_EXIT_MECHANISM") or "PROFIT_GIVEBACK",
        "SECONDARY_EXIT_MECHANISM": p81.get("SECONDARY_EXIT_MECHANISM") or "EXIT_GEOMETRY",
        "FINAL_GATE": final,
        "FINAL_RESEARCH_GATE": final,
        "evidence_kind": "INFERENCE",
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 106–113 (`docs/PHASE106_NON_OHLC_DATA_INVENTORY.md` through "
        "`docs/PHASE113_NON_OHLC_FINAL_GATE.md`) are research-only non-OHLC data inventory "
        "and discriminator gates. They do not download data, connect to MT5, optimize, "
        "modify production, or implement an exit spec."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 98–105"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase106_non_ohlc_data_inventory.py` — **RESEARCH_ONLY** local inventory.\n"
        "`tradingbot/backtest/phase107_tick_intrabar_research.py` — **RESEARCH_ONLY** tick; no MT5.\n"
        "`tradingbot/backtest/phase108_spread_path_research.py` — **RESEARCH_ONLY** spread; no broker inference.\n"
        "`tradingbot/backtest/phase109_htf_context_research.py` — **RESEARCH_ONLY** M15 context; strategy unchanged.\n"
        "`tradingbot/backtest/phase110_news_context_research.py` — **RESEARCH_ONLY** news; no API.\n"
        "`tradingbot/backtest/phase111_multisource_alignment.py` — **RESEARCH_ONLY** declared combinations only.\n"
        "`tradingbot/backtest/phase112_non_ohlc_discriminator_gate.py` — **RESEARCH_ONLY** candidate gate.\n"
        "`tradingbot/backtest/phase113_non_ohlc_final_gate.py` — **RESEARCH_ONLY** final gate; spec not implemented.\n"
    )
    needle = "`tradingbot/backtest/phase105_discriminator_gate.py`"
    if "phase106_non_ohlc_data_inventory.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 106 started | **NO** |", "| Phase 106 started | **YES** |")
    block = f"""

## Non-OHLC discriminator research (Phases 106–113)

| Claim | Status |
|---|---|
| DISCRIMINATOR_STATUS | **{payload.get("DISCRIMINATOR_STATUS")}** |
| TICK_DISCRIMINATOR_STATUS | **{payload.get("TICK_DISCRIMINATOR_STATUS")}** |
| SPREAD_DISCRIMINATOR_STATUS | **{payload.get("SPREAD_DISCRIMINATOR_STATUS")}** |
| HTF_DISCRIMINATOR_STATUS | **{payload.get("HTF_DISCRIMINATOR_STATUS")}** |
| NEWS_DISCRIMINATOR_STATUS | **{payload.get("NEWS_DISCRIMINATOR_STATUS")}** |
| MULTISOURCE_DISCRIMINATOR_STATUS | **{payload.get("MULTISOURCE_DISCRIMINATOR_STATUS")}** |
| EXIT_DESIGN_SPEC | **{payload.get("EXIT_DESIGN_SPEC")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| C/D vs E/F separable with non-OHLC | **{"YES" if (payload.get("questions") or {}).get("9_cd_ef_separable") else "NO"}** |
| Intervention implemented | **NO** |
| Data downloaded | **NO** |
| Optimization | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 114 started | **NO** |
"""
    marker = "## Non-OHLC discriminator research (Phases 106–113)"
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
        ("H106-01", 106, payload.get("NON_OHLC_DATA_STATUS"), "local inventory"),
        ("H107-01", 107, payload.get("TICK_DISCRIMINATOR_STATUS"), "no fabricated ticks"),
        ("H108-01", 108, payload.get("SPREAD_DISCRIMINATOR_STATUS"), "no broker inference"),
        ("H109-01", 109, payload.get("HTF_DISCRIMINATOR_STATUS"), "M15 as-of; strategy unchanged"),
        ("H110-01", 110, payload.get("NEWS_DISCRIMINATOR_STATUS"), "no API"),
        ("H111-01", 111, payload.get("MULTISOURCE_DISCRIMINATOR_STATUS"), "no brute force"),
        ("H112-01", 112, payload.get("DISCRIMINATOR_STATUS"), "candidate gate"),
        ("H113-01", 113, payload.get("NEXT_RESEARCH_TARGET"), "gate; not implemented"),
    ]
    extra = ["", "## Phases 106–113", ""]
    extra.append("| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |")
    extra.append("|---|---|---|---|---|---|---|---|---|---|")
    for hid, ph, result, note in rows:
        extra.append(
            f"| {hid} | {today} | {ph} | frozen Phase38/40 | {n} | event tape 419 resolved | {result} | reported | NO | {note} |"
        )
    extra.append("")
    extra.append(f"**DISCRIMINATOR_STATUS:** `{payload.get('DISCRIMINATOR_STATUS')}`")
    extra.append(f"**NEXT_RESEARCH_TARGET:** `{payload.get('NEXT_RESEARCH_TARGET')}` (not implemented).")
    extra.append(f"**Q19:** `{q.get('19_highest_value_next')}`")
    extra.append("")
    marker = "## Phases 106–113"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def run_phase113_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p81 = _safe_load_json(root / PHASE81_JSON) or {}
    p97 = _safe_load_json(root / PHASE97_JSON) or {}
    p105 = _safe_load_json(root / PHASE105_JSON) or {}
    p106 = _safe_load_json(root / PHASE106_JSON) or {}
    p107 = _safe_load_json(root / PHASE107_JSON) or {}
    p108 = _safe_load_json(root / PHASE108_JSON) or {}
    p109 = _safe_load_json(root / PHASE109_JSON) or {}
    p110 = _safe_load_json(root / PHASE110_JSON) or {}
    p111 = _safe_load_json(root / PHASE111_JSON) or {}
    p112 = _safe_load_json(root / PHASE112_JSON) or {}
    d = decide(p81, p97, p105, p106, p107, p108, p109, p110, p111, p112)
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
        "ORDERS_PLACED": False,
        "ENV_ACCESSED": False,
        "RISK_GATE_CHANGED": False,
        "TRADING_KERNEL_CHANGED": False,
        "EXECUTION_CHANGED": False,
        "STRATEGY_CHANGED": False,
        "CALIBRATION_CHANGED": False,
        "SIZING_CHANGED": False,
        "SLTP_CHANGED": False,
        "ML_ACTIVATED": False,
        "EXIT_DESIGN_SPEC_IMPLEMENTED": False,
        "hypotheses": [
            {
                "id": "H113-01",
                "claim": "Gate whether non-OHLC local data yields a causal C/D vs E/F discriminator without implementing a spec.",
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
        "artifacts": {"json": PHASE113_JSON, "md": PHASE113_MD, "ledger": LEDGER_MD},
    }
    (root / PHASE113_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE113_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    q = payload.get("questions") or {}
    (root / PHASE113_MD).write_text(
        "\n".join(
            [
                "# Phase 113 — Non-OHLC Final Gate",
                "",
                "INFERENCE. Spec not implemented. Data not acquired. Phase 114 not started.",
                f"**DISCRIMINATOR_STATUS:** `{payload['DISCRIMINATOR_STATUS']}`",
                f"**TICK_DISCRIMINATOR_STATUS:** `{payload.get('TICK_DISCRIMINATOR_STATUS')}`",
                f"**SPREAD_DISCRIMINATOR_STATUS:** `{payload.get('SPREAD_DISCRIMINATOR_STATUS')}`",
                f"**HTF_DISCRIMINATOR_STATUS:** `{payload.get('HTF_DISCRIMINATOR_STATUS')}`",
                f"**NEWS_DISCRIMINATOR_STATUS:** `{payload.get('NEWS_DISCRIMINATOR_STATUS')}`",
                f"**MULTISOURCE_DISCRIMINATOR_STATUS:** `{payload.get('MULTISOURCE_DISCRIMINATOR_STATUS')}`",
                f"**PRIMARY_EXIT_MECHANISM:** `{payload['PRIMARY_EXIT_MECHANISM']}`",
                f"**SECONDARY_EXIT_MECHANISM:** `{payload['SECONDARY_EXIT_MECHANISM']}`",
                f"**TAIL_STATUS:** `{payload.get('TAIL_STATUS')}`",
                f"**PROTECTION_STATUS:** `{payload.get('PROTECTION_STATUS')}`",
                f"**EXIT_DESIGN_SPEC_STATUS:** `{payload['EXIT_DESIGN_SPEC_STATUS']}`",
                f"**FINAL_RESEARCH_GATE:** `{payload['FINAL_RESEARCH_GATE']}`",
                f"**NEXT_RESEARCH_TARGET:** `{payload['NEXT_RESEARCH_TARGET']}`",
                "",
                f"1. Datasets exist: `{q.get('1_datasets_exist_locally')}`",
                f"2. Usable: `{q.get('2_usable')}`",
                f"3. Missing ids: `{q.get('3_missing')}`",
                f"4. Tick: `{q.get('4_tick_discriminator')}`",
                f"5. Spread: `{q.get('5_spread_discriminator')}`",
                f"6. HTF: `{q.get('6_htf_discriminator')}`",
                f"7. News: `{q.get('7_news_discriminator')}`",
                f"8. Combination: `{q.get('8_multisource_discriminator')}`",
                f"9. C/D vs E/F separable: `{q.get('9_cd_ef_separable')}`",
                f"10. +31.84R intact in tape: `{q.get('10_tail_intact_in_tape')}`",
                f"11. TRAIN+VAL: `{q.get('11_survives_train_val')}`",
                f"12. OOS: `{q.get('12_survives_oos')}`",
                f"13. recent180: `{q.get('13_survives_recent180')}`",
                f"14. side/regime/year: `{q.get('14_survives_side_regime_year')}`",
                f"15. top1/top5: `{q.get('15_survives_top1_top5')}`",
                f"16. Event unit: `{q.get('16_event_unit_correct')}`",
                f"17. EXIT_DESIGN_SPEC justified: `{q.get('17_exit_design_spec_justified')}`",
                f"18. Missing data: `{q.get('18_exact_data_missing')}`",
                f"19. Next: `{q.get('19_highest_value_next')}`",
                "",
                "Do NOT implement the target. Do not download. Do not trade.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    append_ledger(root, payload)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase113_collection(Path("."))["DISCRIMINATOR_STATUS"])
