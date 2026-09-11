def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phase 118 (`docs/PHASE118_TICK_FORENSIC_VALIDATION.md`) is research-only forensic "
        "validation of the operator-dropped XAUUSD_i MT5 tick export. It does not connect to MT5, "
        "read .env, modify production, implement an exit spec, or start Phase 119."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    text = text.replace(
        "or start Phase 118.",
        "or claim Phase 118 without validating the operator export.",
    )
    if line not in text:
        marker = "Phase 117 (`docs/PHASE117_OPERATOR_SOURCE_RESOLUTION.md`)"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
        else:
            text = text.rstrip() + "\n\n" + line + "\n"
    src.write_text(text, encoding="utf-8")

    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase118_tick_forensic_validation.py` -- **RESEARCH_ONLY** "
        "tick forensic validation; no MT5; no .env; no Phase 119.\n"
    )
    needle = "`tradingbot/backtest/phase117_operator_source_resolution.py`"
    if "phase118_tick_forensic_validation.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 118 started | **NO** |", "| Phase 118 started | **YES** |")
    block = f"""

## Tick forensic validation (Phase 118)

| Claim | Status |
|---|---|
| PHASE118_STATUS | **{payload.get("PHASE118_STATUS")}** |
| DATA_ACQUIRED | **{"YES" if payload.get("DATA_ACQUIRED") else "NO"}** |
| SOURCE_IDENTITY_STATUS | **{payload.get("SOURCE_IDENTITY_STATUS")}** |
| HISTORY_RANGE_STATUS | **{payload.get("HISTORY_RANGE_STATUS")}** |
| BID_ASK_STATUS | **{payload.get("BID_ASK_STATUS")}** |
| DATA_QUALITY_STATUS | **{payload.get("DATA_QUALITY_STATUS")}** |
| TICK_EVENT_COVERAGE | **{payload.get("TICK_EVENT_COVERAGE")}** |
| AMBIGUOUS_394_RESOLVED | **{payload.get("AMBIGUOUS_394_RESOLVED")}** |
| AMBIGUOUS_394_REMAINING | **{payload.get("AMBIGUOUS_394_REMAINING")}** |
| OUTLIER_31_84R_COVERAGE | **{payload.get("OUTLIER_31_84R_COVERAGE")}** |
| C_D_E_F_STATUS | **{payload.get("C_D_E_F_STATUS")}** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 118 started | **YES** |
| Phase 119 started | **NO** |
"""
    marker = "## Tick forensic validation (Phase 118)"
    if marker in ktext:
        start = ktext.find(marker)
        ku.write_text(ktext[:start].rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    extra = [
        "",
        "## Phase 118",
        "",
        "| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |",
        "|---|---|---|---|---|---|---|---|---|---|",
        (
            f"| H118-01 | {today} | 118 | operator export Jul-Sep 2026 | 419 | "
            f"event tape 419 resolved | {payload.get('PHASE118_STATUS')} | reported | NO | "
            f"tick forensic; Phase 119 not started |"
        ),
        "",
        f"**PHASE118_STATUS:** `{payload.get('PHASE118_STATUS')}`",
        f"**HISTORY_RANGE_STATUS:** `{payload.get('HISTORY_RANGE_STATUS')}`",
        f"**TICK_EVENT_COVERAGE:** `{payload.get('TICK_EVENT_COVERAGE')}`",
        f"**AMBIGUOUS_394_RESOLVED:** `{payload.get('AMBIGUOUS_394_RESOLVED')}`",
        f"**AMBIGUOUS_394_REMAINING:** `{payload.get('AMBIGUOUS_394_REMAINING')}`",
        f"**OUTLIER_31_84R_COVERAGE:** `{payload.get('OUTLIER_31_84R_COVERAGE')}`",
        "",
    ]
    marker = "## Phase 118"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE118_STATUS",
        "RAW_FILE_PRESENT",
        "RAW_FILE_PATH",
        "RAW_FILE_SIZE",
        "RAW_FILE_ROWS",
        "RAW_FILE_SHA256",
        "SOURCE_IDENTITY_STATUS",
        "HISTORY_RANGE_STATUS",
        "ACTUAL_FIRST_TICK",
        "ACTUAL_LAST_TICK",
        "BID_ASK_STATUS",
        "TIMESTAMP_STATUS",
        "SPREAD_STATUS",
        "DATA_QUALITY_STATUS",
        "TICK_EVENT_COVERAGE",
        "TICK_COMPLETE_LIFECYCLE_EVENTS",
        "TICK_INTRABAR_RESOLUTION_COVERAGE",
        "AMBIGUOUS_394_RESOLVED",
        "AMBIGUOUS_394_REMAINING",
        "FAVORABLE_FIRST",
        "ADVERSE_FIRST",
        "SIMULTANEOUS_UNRESOLVED",
        "DATA_INSUFFICIENT",
        "OUTLIER_31_84R_COVERAGE",
        "OUTLIER_31_84R_CHRONOLOGY_STATUS",
        "C_D_E_F_STATUS",
        "DATA_ACQUIRED",
        "MT5_USED",
        "ENV_ACCESSED",
        "EXIT_DESIGN_SPEC_IMPLEMENTED",
        "LIVE_TRADING",
        "ORDERS_PLACED",
        "PRODUCTION_CHANGED",
        "OPTIMIZATION_USED",
        "REMAINING_UNKNOWN",
        "NEXT_PHASE_RECOMMENDATION",
        "TESTS_PHASE118",
        "REGRESSION_40_43_57_63_68_118",
        "FROZEN_PHASE40_TIMESTAMP",
        "FROZEN_PHASE40_FINGERPRINT",
        "FROZEN_PHASE40_SHA256",
    ]
    lines = [
        "# Phase 118 - Tick Forensic Validation",
        "",
        "RESEARCH ONLY. Forensic validation of operator-dropped LiteFinance XAUUSD_i MT5 ticks.",
        "No programmatic MT5. No .env. Raw export preserved unchanged. No Phase 119.",
        "",
        "## Timestamp convention",
        "",
        "MT5 `<DATE>` + `<TIME>` combined and **treated as UTC** "
        "(export end aligns with requested UTC window).",
        "",
        "## Quote-state carry-forward",
        "",
        QUOTE_CARRY_FORWARD_NOTE + ".",
        "RAW missing bid/ask counts are reported before forward-fill. Raw file is never rewritten.",
        "",
    ]
    for k in keys:
        lines.append(f"{k} = {payload.get(k)}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "MT5_USED = False. ENV_ACCESSED = False. EXIT_DESIGN_SPEC_IMPLEMENTED = False.",
            "Phase 119 was not started. Frozen Phase40 tape untouched.",
            "",
            f"Canonical symbol: {CANONICAL_SYMBOL}. Rejected: {', '.join(sorted(REJECT_SYMBOLS))}.",
            f"Logical symbol forbidden: {LOGICAL_SYMBOL}.",
            "",
        ]
    )
    (root / PHASE118_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
