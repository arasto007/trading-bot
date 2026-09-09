"""Phase 43 — account-specific cost closure, identity, telemetry, readiness.

RESEARCH ONLY. Attaches MT5 only if already running. Does not launch MT5,
trade, read .env, import live.py, rerun Phase 40, or start Phase 44.
Does not invent a VERIFIED commission schedule.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    evaluate_ev_eq_01,
    login_identity_hash,
)
from tradingbot.backtest.phase42_broker_cost_execution_closure import (
    CANONICAL_SYMBOL,
    LOGICAL_SYMBOL,
    attach_if_running,
    audit_sidecars,
    bounded_tick_probe,
    classify_commission,
    classify_mapping,
    inspect_history,
    inspect_journal,
    is_gold_symbol,
)
from tradingbot.backtest.phase42_cost_reconstruction import reconstruct_frozen_phase40

PHASE = "43"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE43_MD = "docs_v2/02_research/PHASE43_BROKER_COST_EXECUTION_VALIDATION.md"
PHASE43_GATES_MD = "docs_v2/02_research/PHASE43_COST_GATE_STATUS.md"
PHASE43_READY_MD = "docs_v2/02_research/PHASE43_EXECUTABLE_READINESS.md"
PHASE39_JSON = "logs/phase39_broker_economics_execution.json"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE41_JSON = "logs/phase41_final_evidence_closure.json"
PHASE42_JSON = "logs/phase42_broker_cost_execution_closure.json"
PHASE2716_JSON = "logs/phase27_16_FINAL_VALIDATION_GATE.json"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"
BLOCKED = "BLOCKED"
PRODUCT_TOKENS = ("ECN", "CLASSIC", "CENT")
REDACT_KEYS = frozenset(
    {
        "login",
        "password",
        "mt5_password",
        "token",
        "api_key",
        "investor",
        "name",
        "balance",
        "credit",
        "profit",
        "equity",
        "margin",
        "margin_free",
        "margin_level",
        "assets",
        "liabilities",
    }
)
SAFE_ACCOUNT_KEYS = (
    "trade_mode",
    "company",
    "server",
    "currency",
    "leverage",
    "margin_mode",
    "limit_orders",
    "trade_allowed",
    "trade_expert",
    "fifo_close",
    "margin_so_mode",
)
PUBLIC_DOCS = (
    {
        "url": "https://www.litefinance.org/trading/account-types/ecn/",
        "product_claimed": "ECN",
        "commission": "Yes — precious metals $5/lot MT4/MT5 charged at open",
        "applies_to_this_account": False,
        "grade": "OFFICIAL_BROKER_GENERAL_DOCUMENT",
        "fetched_utc": "2026-09-08",
    },
    {
        "url": "https://www.litefinance.org/trading/account-types/classic/",
        "product_claimed": "CLASSIC",
        "commission": "None (spread from 1.8 points; markup, not a separate commission)",
        "applies_to_this_account": False,
        "grade": "OFFICIAL_BROKER_GENERAL_DOCUMENT",
        "fetched_utc": "2026-09-08",
    },
    {
        "url": "https://www.litefinance.org/uploads/documents/pdf-litefinance/litefinance-markups-and-commissions-list-en.pdf",
        "product_claimed": "ECN vs CLASSIC/CENT grid",
        "commission": "ECN XAUUSD $5; CLASSIC/CENT XAUUSD markup 14 (effective 2026-03-26)",
        "applies_to_this_account": False,
        "grade": "OFFICIAL_BROKER_GENERAL_DOCUMENT",
        "fetched_utc": "2026-09-08",
    },
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account_product",
    "commission",
    "symbol",
    "ev_eq_01",
    "swap",
    "spread",
    "slippage",
    "request_fill",
    "execution",
    "cost_gates",
    "cost_margin",
    "executable_contract",
    "horizon_reconciliation",
    "dependence",
    "final_gate",
    "verdict",
    "production_safety",
    "artifacts",
)
FROZEN_PHASE40 = {
    "tape_rows_loaded": 250000,
    "signals": 2847,
    "buy": 1063,
    "sell": 1784,
    "events": 420,
    "win_rate": 0.314528,
    "expectancy_R": 0.017224,
    "profit_factor": 1.025128,
    "max_drawdown_R": 293.59309,
    "oos_signals": 367,
    "oos_events": 63,
    "allowed": 82,
    "rejected": 2765,
    "fills": 0,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def detect_product_tokens(fields: dict[str, Any]) -> dict[str, Any]:
    hits: list[dict[str, str]] = []
    scanned: list[str] = []
    for key, value in fields.items():
        if str(key).lower() in REDACT_KEYS:
            continue
        scanned.append(str(key))
        text = str(value or "")
        upper = text.upper()
        for token in PRODUCT_TOKENS:
            if re.search(rf"\b{token}\b", upper):
                hits.append({"field": str(key), "token": token})
    unique = sorted({h["token"] for h in hits})
    product = unique[0] if len(unique) == 1 else UNKNOWN
    return {
        "account_product_type": product,
        "hits": hits,
        "identifier_fields_scanned": scanned,
        "inferred_from_zero_commission": False,
        "inferred_from_broker_name": False,
        "inferred_from_balance": False,
        "ambiguous": len(unique) > 1,
    }


def collect_account_product(mt5: Any) -> dict[str, Any]:
    acct = mt5.account_info()
    raw: dict[str, Any] = {}
    keys: list[str] = []
    if acct is not None:
        try:
            raw = dict(acct._asdict())  # noqa: SLF001 — read-only
            keys = sorted(str(k) for k in raw)
        except Exception:
            keys = [str(k) for k in dir(acct) if not str(k).startswith("_")]
            raw = {k: getattr(acct, k, UNKNOWN) for k in keys}
    sanitized = {k: raw.get(k) for k in SAFE_ACCOUNT_KEYS if k in raw}
    scan_fields = {k: v for k, v in raw.items() if str(k).lower() not in REDACT_KEYS}
    detected = detect_product_tokens(scan_fields)
    status = "VERIFIED" if detected["account_product_type"] not in ("", UNKNOWN) else UNKNOWN
    return {
        "ACCOUNT_PRODUCT_STATUS": status,
        "broker": sanitized.get("company") or UNKNOWN,
        "server": sanitized.get("server") or UNKNOWN,
        "account_type": sanitized.get("trade_mode"),
        "account_product": detected["account_product_type"],
        "account_tier": UNKNOWN,
        "applicability": "NOT_PROVEN",
        "evidence_source": "MT5 account_info sanitized identifiers + official public pages (supporting only)",
        "timestamp": _utc_now(),
        "login_identity": login_identity_hash(raw.get("login")),
        "visible_account_keys": keys,
        "sanitized_non_sensitive": sanitized,
        "product_scan": detected,
        "note": "Product is not inferred from zeros, broker name, balance, leverage, or server.",
    }


def scan_deal_comments(mt5: Any) -> dict[str, Any]:
    from datetime import datetime as dt

    deals = mt5.history_deals_get(dt(2018, 1, 1, tzinfo=timezone.utc), dt.now(timezone.utc)) or []
    comments = []
    gold = 0
    for deal in deals:
        if is_gold_symbol(str(getattr(deal, "symbol", "") or "")):
            gold += 1
            comment = str(getattr(deal, "comment", "") or "")
            if comment:
                comments.append(comment)
    tokens = [c for c in comments if any(re.search(rf"\b{t}\b", c.upper()) for t in PRODUCT_TOKENS)]
    return {
        "gold_deals": gold,
        "comments_present": int(len(comments)),
        "product_token_comments": tokens[:20],
        "proves_account_product": False,
    }


def cost_margin(p40: dict[str, Any], p42: dict[str, Any]) -> dict[str, Any]:
    raw = float(((p40.get("raw_performance") or {}).get("expectancy_R")) or FROZEN_PHASE40["expectancy_R"])
    scenarios = {row.get("id"): row for row in ((p40.get("cost_sensitivity") or {}).get("scenarios") or [])}
    modeled = scenarios.get("MODELED_1X") or {}
    modeled_exp = modeled.get("signal_expectancy_R")
    modeled_drag = None if modeled_exp is None else raw - float(modeled_exp)
    swap = ((p42.get("swap") or {}).get("modeled_sensitivity") or {})
    swap_drag = swap.get("expected_drag_if_share_overnight_long_R")
    uncertainty_gt_edge = bool(
        (modeled_drag is not None and modeled_drag > abs(raw))
        or (isinstance(swap_drag, (int, float)) and abs(float(swap_drag)) > abs(raw))
    )
    return {
        "RAW_EXPECTANCY_R": raw,
        "OBSERVED_COST": "current swap rates OBSERVED; historical swap UNKNOWN; 15d sidecar spread OBSERVED",
        "MODELED_COST": {
            "MODELED_1X_signal_expectancy_R": modeled_exp,
            "MODELED_1X_drag_R": modeled_drag,
            "swap_overnight_long_share_drag_R": swap_drag,
            "label": "MODELED / SCENARIO — not verified broker PnL",
        },
        "UNKNOWN_COST": ["commission", "historical swap series", "eval-tape Bid/Ask", "request/fill slippage"],
        "uncertainty_exceeds_raw_edge": uncertainty_gt_edge,
        "COST_MARGIN": "INSUFFICIENT / UNKNOWN",
        "verified_cost_margin": UNKNOWN,
        "modeled_cost_margin": "INSUFFICIENT",
        "survives_costs_claimed": False,
        "note": (
            "MODELED_1X already flips RAW +0.017224R to about -0.061R. "
            "That is not a verified cost proof, but it shows modeled cost uncertainty exceeds the raw edge. "
            "Commission remains UNKNOWN and is not converted to zero."
        ),
    }


def cost_gates(p42: dict[str, Any], product: dict[str, Any], comm: dict[str, Any]) -> dict[str, Any]:
    prior = (p42.get("cost_gates") or {}).get("rows") or []
    rows = []
    for row in prior:
        rows.append({**row, "phase42_status": row.get("status")})
    if not rows:
        rows = [
            {"gate": "1 symbol identity", "status": "FAIL", "note": "EV-EQ-01 NOT_PROVEN"},
            {"gate": "2 broker economics", "status": "PARTIAL", "note": "current REAL XAUUSD_i OBSERVED"},
            {"gate": "3 commission", "status": "FAIL", "note": comm.get("status")},
            {"gate": "4 swap", "status": "PARTIAL", "note": "CURRENT OBSERVED / HISTORICAL UNKNOWN"},
            {"gate": "5 historical spread", "status": "PARTIAL", "note": "sidecar PARTIAL; eval tape PROXY"},
            {"gate": "6 slippage", "status": "FAIL", "note": "MODELED"},
            {"gate": "7 execution evidence", "status": "PARTIAL", "note": "PARTIAL_EXECUTION_EVIDENCE"},
            {"gate": "8 request/fill telemetry", "status": "FAIL", "note": "pairs=0"},
        ]
    if product.get("ACCOUNT_PRODUCT_STATUS") == UNKNOWN:
        for row in rows:
            if str(row.get("gate", "")).startswith("3"):
                row["status"] = "FAIL"
                row["note"] = "UNKNOWN — account product still unproven; official pages supporting only"
    counts = {
        "PASS_COUNT": sum(1 for r in rows if r.get("status") == "PASS"),
        "PARTIAL_COUNT": sum(1 for r in rows if r.get("status") == "PARTIAL"),
        "FAIL_COUNT": sum(1 for r in rows if r.get("status") == "FAIL"),
        "UNKNOWN_COUNT": sum(1 for r in rows if r.get("status") == "UNKNOWN"),
    }
    return {
        "rows": rows,
        **counts,
        "cost_ready_gate_count": counts["PASS_COUNT"],
        "required": 8,
        "vs_phase42": "unchanged — no gate promoted to PASS",
        "modeled_not_pass": True,
    }


def executable_contract(comm: dict[str, Any], mapping: dict[str, Any], pairs: int) -> dict[str, Any]:
    ready = bool(comm.get("verified_schedule")) and mapping.get("SYMBOL_MAPPING") in {"VERIFIED_EQUIVALENT", "VERIFIED_DIFFERENT"}
    return {
        "EXECUTABLE_READY": False if comm.get("status") == UNKNOWN else bool(ready),
        "readiness": "BLOCKED",
        "checklist": {
            "symbol_identity": mapping.get("SYMBOL_MAPPING") or NOT_PROVEN,
            "contract_economics": "OBSERVED on XAUUSD_i",
            "volume_rules": "OBSERVED on XAUUSD_i",
            "spread": "PARTIAL / PROXY",
            "commission": comm.get("status") or UNKNOWN,
            "swap": "CURRENT OBSERVED / HISTORICAL UNKNOWN",
            "slippage": "MODELED",
            "execution_assumptions": "PARTIAL",
            "entry_exit_prices": "OBSERVED Phase 40 theoretical",
            "SL_TP": "OBSERVED Phase 40",
            "holding_duration": "OBSERVED Phase 40",
        },
        "blockers": [
            "commission UNKNOWN / no VERIFIED_SCHEDULE",
            "request/fill pairs=0",
            "eval-tape Bid/Ask incomplete",
            "EV-EQ-01 NOT_PROVEN",
        ],
        "sensitivity_only_allowed": True,
        "sensitivity_run": False,
        "executable_evaluation_run": False,
        "engine_changed": False,
        "unknown_not_converted_to_zero": True,
    }


def horizon_reconciliation(p40: dict[str, Any]) -> dict[str, Any]:
    cmp_ = p40.get("comparison_180_vs_full") or {}
    latest = cmp_.get("latest_180d_of_full_scan") or {}
    isolated = cmp_.get("phase38_isolated_180d_sliced_enrich") or {}
    oos = p40.get("oos_sufficiency") or {}
    return {
        "phase39_180d_RAW_R": isolated.get("expectancy_R") or -0.591085,
        "phase40_full_RAW_R": ((p40.get("raw_performance") or {}).get("expectancy_R")),
        "phase40_latest_180d_RAW_R": (latest.get("signal") or {}).get("expectancy_R") or -0.467633,
        "phase40_latest_180d_signals": latest.get("signals"),
        "phase40_latest_180d_events": latest.get("events"),
        "oos_signals": oos.get("signals"),
        "oos_events": oos.get("events"),
        "oos_classification": oos.get("classification"),
        "do_not_treat_as_contradiction": True,
        "tiny_positive_full_horizon_robust": False,
        "interpretation": (
            "Full-horizon RAW +0.017224R coexists with recent-180d about -0.47R and Phase 39 isolated 180d about -0.59R. "
            "Different horizons/regimes, not a silent contradiction. The full-horizon edge is not shown to be robust."
        ),
    }


def dependence_note(p40: dict[str, Any]) -> dict[str, Any]:
    dep = p40.get("dependence") or p40.get("events") or {}
    sizes = list(dep.get("sizes") or [])
    total = float(sum(sizes)) if sizes else 0.0
    top = sorted(sizes, reverse=True)
    return {
        "signal_count": dep.get("signal_count") or FROZEN_PHASE40["signals"],
        "event_count": dep.get("event_count") or FROZEN_PHASE40["events"],
        "clustered_signal_share": dep.get("clustered_signal_share"),
        "independence_claimed": bool(dep.get("independence_claimed")),
        "do_not_treat_signals_as_iid": True,
        "top1_share": (top[0] / total) if total and top else UNKNOWN,
        "top5_share": (sum(top[:5]) / total) if total and top else UNKNOWN,
        "top10_share": (sum(top[:10]) / total) if total and top else UNKNOWN,
        "effective_sample_unit": "mechanical_event (420), not 2847 iid signals",
        "rescanned": False,
    }


def _write_docs(root: Path, payload: dict[str, Any]) -> None:
    v = payload.get("verdict") or {}
    ap = payload.get("account_product") or {}
    c = payload.get("commission") or {}
    s = payload.get("symbol") or {}
    ev = payload.get("ev_eq_01") or {}
    contract = payload.get("executable_contract") or {}
    gates = payload.get("cost_gates") or {}
    cm = payload.get("cost_margin") or {}
    hz = payload.get("horizon_reconciliation") or {}
    dep = payload.get("dependence") or {}
    lines = [
        "# Phase 43 — Account-Specific Broker Cost, Identity, Telemetry, Executable Readiness",
        "",
        f"**STATUS:** `{payload.get('status')}`",
        "**Class:** RESEARCH / EVIDENCE-CLOSURE ONLY",
        f"**FINAL_GATE:** `{payload.get('final_gate')}`",
        f"**EXECUTABLE_READY:** `{contract.get('EXECUTABLE_READY')}`",
        f"**OVERALL_VERDICT:** `{v.get('OVERALL_VERDICT')}`",
        f"**PHASE40_RESCAN:** `NO`",
        f"**MT5 launched by phase:** `{((payload.get('mt5') or {}).get('launch') or {}).get('launched_by_phase')}`",
        "",
        "STOP AFTER PHASE 43. DO NOT START PHASE 44.",
        "DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.",
        "",
        "This phase does **not** rewrite Phase 28/39/40/41/42 conclusions.",
        "",
        "## Account product",
        "",
        f"- ACCOUNT_PRODUCT_STATUS: `{ap.get('ACCOUNT_PRODUCT_STATUS')}`",
        f"- Broker/server: `{ap.get('broker')}` / `{ap.get('server')}`",
        f"- Product/tier: `{ap.get('account_product')}` / `{ap.get('account_tier')}`",
        f"- Applicability: `{ap.get('applicability')}`",
        "",
        "Official ECN page: precious metals $5/lot at MT5 open. Official CLASSIC page: commission None.",
        "Neither applies until this account's product/tier is proven. Zeros are not a schedule.",
        "",
        "## Commission / identity / telemetry",
        "",
        f"- COMMISSION: `{c.get('status')}` verified_schedule=`{c.get('verified_schedule')}`",
        f"- CURRENT_TERMINAL_XAUUSD: `{s.get('CURRENT_TERMINAL_XAUUSD')}`",
        f"- SYMBOL_MAPPING: `{s.get('SYMBOL_MAPPING')}`",
        f"- EV-EQ-01: `{ev.get('status')}`",
        f"- REQUEST_FILL_PAIRS: `{(payload.get('request_fill') or {}).get('pairs')}`",
        f"- SLIPPAGE: `{(payload.get('slippage') or {}).get('SLIPPAGE_POLICY')}`",
        f"- HISTORICAL_SWAP: `{(payload.get('swap') or {}).get('HISTORICAL_SWAP')}`",
        f"- SPREAD: `{(payload.get('spread') or {}).get('SPREAD_POLICY')}`",
        "",
        "## Cost margin / horizon / dependence",
        "",
        f"- RAW expectancy: `{cm.get('RAW_EXPECTANCY_R')}` R",
        f"- COST_MARGIN: `{cm.get('COST_MARGIN')}`",
        f"- MODELED_1X expectancy: `{(cm.get('MODELED_COST') or {}).get('MODELED_1X_signal_expectancy_R')}` R",
        f"- Survives costs claimed: `{cm.get('survives_costs_claimed')}`",
        f"- Phase 39 180d: `{hz.get('phase39_180d_RAW_R')}` R",
        f"- Phase 40 latest 180d: `{hz.get('phase40_latest_180d_RAW_R')}` R",
        f"- Clustered signal share: `{dep.get('clustered_signal_share')}`",
        f"- Do not treat 2847 signals as iid: `{dep.get('do_not_treat_signals_as_iid')}`",
        "",
        hz.get("interpretation") or "",
        "",
        "## Executable",
        "",
        f"- EXECUTABLE_READY: `{contract.get('EXECUTABLE_READY')}`",
        f"- Evaluation run: `{contract.get('executable_evaluation_run')}`",
        "",
        "Commission UNKNOWN fail-closes a verified executable evaluation. No fake fills were created.",
        "",
        "## Stop",
        "",
        "STOP AFTER PHASE 43.",
        "DO NOT START PHASE 44.",
        "",
    ]
    (root / PHASE43_MD).write_text("\n".join(lines), encoding="utf-8")
    gate_md = [
        "# Phase 43 — Cost Gate Status",
        "",
        f"**PASS_COUNT:** `{gates.get('PASS_COUNT')}`",
        f"**PARTIAL_COUNT:** `{gates.get('PARTIAL_COUNT')}`",
        f"**FAIL_COUNT:** `{gates.get('FAIL_COUNT')}`",
        f"**UNKNOWN_COUNT:** `{gates.get('UNKNOWN_COUNT')}`",
        "",
        "| Gate | Status | Note |",
        "|---|---|---|",
    ]
    for row in gates.get("rows") or []:
        gate_md.append(f"| {row.get('gate')} | {row.get('status')} | {row.get('note')} |")
    gate_md += ["", "Modeled evidence is never PASS.", f"Vs Phase 42: {gates.get('vs_phase42')}", ""]
    (root / PHASE43_GATES_MD).write_text("\n".join(gate_md), encoding="utf-8")
    ready = [
        "# Phase 43 — Executable Readiness",
        "",
        f"**EXECUTABLE_READY:** `{contract.get('EXECUTABLE_READY')}`",
        f"**Readiness:** `{contract.get('readiness')}`",
        "",
        "Checklist:",
        "",
    ]
    for key, val in (contract.get("checklist") or {}).items():
        ready.append(f"- `{key}`: {val}")
    ready += ["", "Blockers:", ""]
    for b in contract.get("blockers") or []:
        ready.append(f"- {b}")
    ready += [
        "",
        "Unknown commission is not converted to zero.",
        "Verified executable evaluation was **not** run.",
        "No PHASE43_EXECUTABLE_EVALUATION.md was created because evaluation did not run.",
        "",
    ]
    (root / PHASE43_READY_MD).write_text("\n".join(ready), encoding="utf-8")


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phase 43 (`docs_v2/02_research/PHASE43_BROKER_COST_EXECUTION_VALIDATION.md`) is research-only "
        "account-specific broker-cost and executable-readiness closure. It does not authorize live trading, "
        "overwrite the frozen M5 snapshot, optimize, or start Phase 44."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phase 42 (`docs_v2/02_research/PHASE42_BROKER_COST_EXECUTION_CLOSURE.md`)"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    row = (
        "| Phase 43 broker cost/execution validation | `run_phase43_collection()` | n/a | "
        "RESEARCH/AUDIT; attach-if-running only; no bot/orders/.env | "
        f"**{payload.get('status')}**; Phase 44 not started |"
    )
    if "Phase 43 broker cost/execution validation" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", row + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    bline = (
        "`tradingbot/backtest/phase43_broker_cost_execution_validation.py` — **RESEARCH_ONLY** "
        "account-specific cost/identity/telemetry; attach-if-running; does not overwrite Phase 28 M5.\n"
    )
    needle = (
        "`tradingbot/backtest/phase42_broker_cost_execution_closure.py` — **RESEARCH_ONLY** "
        "broker cost/execution telemetry; attach-if-running; does not overwrite Phase 28 M5.\n"
    )
    if "phase43_broker_cost_execution_validation.py" not in btext and needle in btext:
        bnd.write_text(btext.replace(needle, needle + bline), encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 43 started | **NO** |", "| Phase 43 started | **YES** |")
    block = f"""

## Broker cost execution validation (Phase 43)

| Claim | Status |
|---|---|
| Phase 43 status | **{payload.get("status")}** |
| Phase 40 rescan | **NO** |
| Account product | **{((payload.get("account_product") or {}).get("ACCOUNT_PRODUCT_STATUS"))}** |
| Commission | **{((payload.get("commission") or {}).get("status"))}** |
| EV-EQ-01 | **{((payload.get("ev_eq_01") or {}).get("status"))}** |
| Executable ready | **{((payload.get("executable_contract") or {}).get("EXECUTABLE_READY"))}** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Phase 44 started | **NO** |
"""
    if "## Broker cost execution validation (Phase 43)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def run_phase43_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p16 = _safe_load_json(root / PHASE2716_JSON) or {}
    p39 = _safe_load_json(root / PHASE39_JSON) or {}
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p41 = _safe_load_json(root / PHASE41_JSON) or {}
    p42 = _safe_load_json(root / PHASE42_JSON) or {}

    mt5_pack = attach_if_running()
    attach = mt5_pack.get("attach") or {}
    symbols_live = mt5_pack.get("symbols") or {}
    product = {
        "ACCOUNT_PRODUCT_STATUS": UNKNOWN,
        "broker": (p42.get("broker") or {}).get("broker") or "LiteFinance Global LLC",
        "server": (p42.get("broker") or {}).get("server") or "LiteFinance-MT5-Live",
        "account_type": "REAL",
        "account_product": UNKNOWN,
        "account_tier": UNKNOWN,
        "applicability": "NOT_PROVEN",
        "evidence_source": "reused Phase 42 / Phase 27.22 — no product identifier",
        "timestamp": _utc_now(),
        "fresh_scan": False,
    }
    deal_comments = {"gold_deals": None, "proves_account_product": False}
    history: dict[str, Any]
    if attach.get("ok"):
        try:
            import MetaTrader5 as mt5

            product = collect_account_product(mt5)
            product["fresh_scan"] = True
            deal_comments = scan_deal_comments(mt5)
            history = inspect_history(mt5)
        except Exception as exc:
            history = {"status": "BLOCKED", "error": str(exc)[:200], "genuine_requested_vs_filled_pairs": 0}
    else:
        history = {
            "status": "REUSED_PHASE42",
            "deals_total": (p42.get("history") or {}).get("deals_total"),
            "orders_total": (p42.get("history") or {}).get("orders_total"),
            "xauusd_i_deals": (p42.get("history") or {}).get("xauusd_i_deals") or 30,
            "all_xi_commission_zero": (p42.get("history") or {}).get("all_xi_commission_zero", True),
            "genuine_requested_vs_filled_pairs": int((p42.get("request_fill") or {}).get("pairs") or 0),
        }

    journal = inspect_journal(root)
    ticks = {"status": "SKIPPED", "reason": "MT5 not attached"}
    if attach.get("ok"):
        ticks = bounded_tick_probe()
        ticks["new_long_horizon_file_written"] = False
        ticks["reason_not_full_horizon"] = (
            "copy_ticks_range over 1291 days is a known hang risk. Phase 43 kept the 12s/400-tick bound. "
            "Existing sidecars were not overwritten."
        )

    xi = symbols_live.get(CANONICAL_SYMBOL) or ((p42.get("SYMBOL_EVIDENCE_TABLE") or [{}])[0] if p42 else {})
    xau = symbols_live.get(LOGICAL_SYMBOL) or {}
    if not xau:
        for row in p42.get("SYMBOL_EVIDENCE_TABLE") or []:
            if row.get("symbol") == LOGICAL_SYMBOL:
                xau = {**row, "existence": row.get("observed")}
    if xi and "existence" not in xi:
        xi = {**xi, "existence": xi.get("observed") or xi.get("existence") or "YES", "symbol": CANONICAL_SYMBOL}
    if xau and "existence" not in xau:
        xau = {**xau, "existence": xau.get("observed") or "NOT_OBSERVED_ON_THIS_TERMINAL", "symbol": LOGICAL_SYMBOL}

    env = attach.get("environment") or (p42.get("broker") or {}).get("environment") or "REAL"
    server = attach.get("server") or product.get("server") or "LiteFinance-MT5-Live"
    ev = evaluate_ev_eq_01(
        xau if xau.get("existence") == "YES" else None,
        xi if xi.get("existence") == "YES" else None,
        environment=str(env),
        server=str(server),
        artifact=PHASE43_JSON,
        timestamp=_utc_now(),
    )
    mapping = classify_mapping(xi, xau, ev)
    comm = classify_commission(history, p39)
    comm["account_product_type"] = product.get("account_product") or UNKNOWN
    comm["public_docs_supporting_only"] = list(PUBLIC_DOCS)
    comm["deal_comment_product_tokens"] = deal_comments.get("product_token_comments") or []
    comm["verified_schedule"] = False
    comm["status"] = UNKNOWN

    sidecars = audit_sidecars(root)
    spread = {
        "SPREAD_POLICY": "PROXY / PARTIAL",
        "evaluation_tape_bid_ask": False,
        "sidecars": sidecars,
        "tick_probe": ticks,
        "new_full_horizon_acquired": False,
        "covers_1291d_eval_tape": False,
        "canonical_files_overwritten": False,
    }
    pairs = int(history.get("genuine_requested_vs_filled_pairs") or journal.get("xauusd_i_requested_fill_pairs") or 0)
    slip = {
        "SLIPPAGE_EVIDENCE": UNKNOWN,
        "SLIPPAGE_POLICY": "MODELED",
        "pairs": pairs,
        "model_unchanged": True,
    }
    exe = {
        "grade": "PARTIAL_EXECUTION_EVIDENCE",
        "deals": history.get("deals_total") or (p42.get("execution") or {}).get("deals"),
        "orders": history.get("orders_total") or (p42.get("execution") or {}).get("orders"),
        "xauusd_i_deals": history.get("xauusd_i_deals"),
        "requested_vs_executed_price": "NOT_IDENTIFIABLE",
        "history_status": history.get("status"),
    }
    swap = {
        "CURRENT_SWAP": (p42.get("swap") or {}).get("CURRENT_SWAP") or "OBSERVED",
        "HISTORICAL_SWAP": UNKNOWN,
        "SWAP_POLICY": "BROKER_RATE_ONLY",
        "current_swap_long": (p42.get("swap") or {}).get("current_swap_long"),
        "current_swap_short": (p42.get("swap") or {}).get("current_swap_short"),
        "rollover3days": (p42.get("swap") or {}).get("rollover3days"),
        "hold_diagnostics": (p42.get("swap") or {}).get("hold_diagnostics"),
        "modeled_sensitivity": (p42.get("swap") or {}).get("modeled_sensitivity"),
        "historical_series_invented": False,
    }
    if not swap.get("hold_diagnostics"):
        eco = {"tick_size": 0.01, "tick_value": 1.0}
        recon = reconstruct_frozen_phase40(root, eco, swap)
        swap["hold_diagnostics"] = recon.get("hold_diagnostics")
        swap["modeled_sensitivity"] = recon.get("swap_sensitivity")

    gates = cost_gates(p42, product, comm)
    margin = cost_margin(p40, p42)
    contract = executable_contract(comm, mapping, pairs)
    hz = horizon_reconciliation(p40)
    dep = dependence_note(p40)

    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "phase42_acquisition_rerun": False,
        "phase_44_started": False,
        "env_accessed": False,
        "frozen_phase40": FROZEN_PHASE40,
        "phase40_baseline_verified": {
            "signals": (p40.get("raw_performance") or {}).get("setups") or (p40.get("scan") or {}).get("signals"),
            "events": (p40.get("events") or {}).get("event_count"),
            "raw_expectancy_R": (p40.get("raw_performance") or {}).get("expectancy_R"),
            "FINAL_GATE": p40.get("FINAL_GATE"),
            "values_overwritten": False,
        },
        "mt5": {
            "launch": mt5_pack.get("launch"),
            "attach_status": attach.get("status") or ("ATTACHED" if attach.get("ok") else "NOT_ATTACHED"),
            "attach_ok": bool(attach.get("ok")),
            "gold_aliases": mt5_pack.get("gold_aliases"),
        },
        "account_product": product,
        "public_docs": list(PUBLIC_DOCS),
        "deal_comments": deal_comments,
        "commission": comm,
        "symbol": mapping,
        "ev_eq_01": ev,
        "swap": swap,
        "spread": spread,
        "slippage": slip,
        "request_fill": {
            "pairs": pairs,
            "journal_xauusd_i_pairs": journal.get("xauusd_i_requested_fill_pairs"),
            "status": 0 if pairs == 0 else pairs,
        },
        "execution": exe,
        "cost_gates": gates,
        "cost_margin": margin,
        "executable_contract": contract,
        "horizon_reconciliation": hz,
        "dependence": dep,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "prior_phase16_final_gate": p16.get("FINAL_GATE"),
        "verdict": {
            "BROKER_VERDICT": "PARTIALLY_VERIFIED",
            "COMMISSION_VERDICT": "BLOCKED",
            "SWAP_VERDICT": "PARTIALLY_VERIFIED",
            "SPREAD_VERDICT": "INSUFFICIENT_EVIDENCE",
            "SLIPPAGE_VERDICT": "INSUFFICIENT_EVIDENCE",
            "EXECUTION_VERDICT": "INSUFFICIENT_EVIDENCE",
            "SYMBOL_VERDICT": NOT_PROVEN,
            "EV_EQ_01_VERDICT": NOT_PROVEN,
            "COST_VERDICT": "INSUFFICIENT_EVIDENCE",
            "EXECUTABLE_VERDICT": BLOCKED,
            "RAW_STRATEGY_VERDICT": "PROMISING_BUT_UNPROVEN",
            "OOS_VERDICT": "PROMISING_BUT_UNPROVEN",
            "OVERALL_VERDICT": "INSUFFICIENT_EVIDENCE",
            "profitability_verdict": "NOT_ISSUED",
            "EXECUTABLE_RESULT": "BLOCKED",
            "EXECUTABLE_EXPECTANCY": None,
            "COST_DRAG": None,
        },
        "next_actions": [
            {"rank": 1, "action": "Operator confirms LiteFinance cabinet product/tier (ECN vs CLASSIC vs CENT) and account-applicable commission schedule", "information_value": "HIGHEST"},
            {"rank": 2, "action": "Enable request/fill telemetry on XAUUSD_i without trading from this phase", "information_value": "HIGH"},
            {"rank": 3, "action": "Historical Bid/Ask covering the Phase 38/40 evaluation tape", "information_value": "HIGH"},
            {"rank": 4, "action": "EV-EQ-01: observe XAUUSD on REAL catalog or official equivalence statement", "information_value": "HIGH"},
            {"rank": 5, "action": "Verified executable evaluation after commission VERIFIED_SCHEDULE — then event/OOS, not optimization", "information_value": "HIGHEST_AFTER_COSTS"},
        ],
        "parameters_optimized": False,
        "datasets_changed": False,
        "silent_xauusd_mapping": False,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "DAEMON": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "RISK_GATE": "NOT_MODIFIED",
            "STRATEGY": "NOT_MODIFIED",
            "EXECUTION_ROUTER": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "MT5_LAUNCHED": False,
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {
            "json": PHASE43_JSON,
            "md": PHASE43_MD,
            "gates_md": PHASE43_GATES_MD,
            "ready_md": PHASE43_READY_MD,
            "executable_eval_md": None,
        },
        "legacy_ml_phase43_not_this_phase": ["tests/test_phase43.py"],
        "phase41_artifact_present": bool(p41),
    }
    _write_json(root / PHASE43_JSON, payload)
    _write_docs(root, payload)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    out = run_phase43_collection(Path("."))
    print("STATUS", out.get("status"))
    print("PRODUCT", (out.get("account_product") or {}).get("ACCOUNT_PRODUCT_STATUS"))
    print("COMMISSION", (out.get("commission") or {}).get("status"))
    print("EV-EQ-01", (out.get("ev_eq_01") or {}).get("status"))
    print("READY", ((out.get("executable_contract") or {}).get("EXECUTABLE_READY")))
    print("FINAL_GATE", out.get("final_gate"))
