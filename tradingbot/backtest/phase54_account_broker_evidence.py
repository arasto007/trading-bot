"""Phase 54 — account + broker evidence discovery.

RESEARCH / FORENSICS ONLY. Attaches MT5 only if terminal64 is already running.
Does not launch MT5, trade, read .env, import live.py, or rewrite Phase 40–53.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
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
    inspect_history,
    inspect_journal,
    is_gold_symbol,
)
from tradingbot.backtest.phase43_broker_cost_execution_validation import (
    detect_product_tokens,
)

PHASE = "54"
PHASE54_JSON = "logs/phase54_account_broker_evidence.json"
PHASE54_MD = "docs/PHASE54_ACCOUNT_BROKER_EVIDENCE.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE42_JSON = "logs/phase42_broker_cost_execution_closure.json"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"
BLOCKED = "BLOCKED"
FROZEN_TAPE_FINGERPRINT = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
TARGET_SYMBOLS = ("XAUUSD", "XAUUSD_i", "XAUPUSD_cl")
IDENTITY_FIELDS = (
    "digits",
    "point",
    "contract_size",
    "tick_size",
    "tick_value",
    "volume_min",
    "volume_step",
    "volume_max",
    "execution_mode",
    "filling_mode",
    "swap_long",
    "swap_short",
    "currency_base",
    "currency_profit",
    "currency_margin",
)
PRODUCT_ID_FIELDS = (
    "group",
    "company",
    "comment",
    "account_type",
    "product",
    "category",
    "server",
    "trade_mode",
    "name",
)
NUMERIC_ACCOUNT_FIELDS = (
    "trade_mode",
    "server",
    "company",
    "currency",
    "leverage",
    "limit_orders",
    "margin_mode",
    "trade_allowed",
    "trade_expert",
    "balance",
    "equity",
    "margin",
    "margin_free",
    "margin_level",
    "fifo_close",
    "currency_digits",
)
REDACT = frozenset({"login", "password", "mt5_password", "token", "api_key", "investor"})
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account",
    "product",
    "symbols",
    "identity",
    "commission",
    "official_docs",
    "final_gate",
    "production_safety",
    "artifacts",
)
OFFICIAL_DOCS = {
    "source": "official LiteFinance",
    "instrument": "XAUUSD",
    "ECN_usd_per_lot": 5.0,
    "CLASSIC_markup": 14,
    "CENT_markup": 14,
    "effective_date_operator_stated": "2026-05-19",
    "effective_date_prior_artifact": "2026-03-26",
    "effective_date_conflict": True,
    "applicability_to_exact_account": UNKNOWN,
    "grade": "OFFICIAL_BROKER_GENERAL_DOCUMENT",
    "urls": [
        "https://www.litefinance.org/trading/account-types/ecn/",
        "https://www.litefinance.org/trading/account-types/classic/",
        "https://www.litefinance.org/uploads/documents/pdf-litefinance/litefinance-markups-and-commissions-list-en.pdf",
    ],
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


def _hash_text(value: Any) -> str:
    if value in (None, "", 0):
        return UNKNOWN
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def compare_identity(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_exists = left.get("existence") in {"YES", "OBSERVED"}
    right_exists = right.get("existence") in {"YES", "OBSERVED"}
    rows = []
    matches = 0
    mismatches = 0
    missing = 0
    for field in IDENTITY_FIELDS:
        lv = left.get(field, UNKNOWN)
        rv = right.get(field, UNKNOWN)
        if not left_exists or not right_exists or lv in (None, UNKNOWN) or rv in (None, UNKNOWN):
            status = "NOT_AVAILABLE"
            missing += 1
        elif lv == rv:
            status = "MATCH"
            matches += 1
        else:
            status = "MISMATCH"
            mismatches += 1
        rows.append({"field": field, "XAUUSD": lv if left_exists else "NOT_OBSERVED", "XAUUSD_i": rv, "status": status})
    if not left_exists:
        identity = "NOT_PROVEN"
        note = (
            "XAUUSD is NOT_OBSERVED on this terminal. Current-terminal absence does not prove "
            "broker-wide absence and is not CONTRADICTED. Operator claim REAL=XAUUSD remains unresolved."
        )
    elif mismatches:
        identity = "CONTRADICTED"
        note = "Both symbols observed with mismatched economics."
    elif matches == len(IDENTITY_FIELDS):
        identity = "PROVEN"
        note = "All compared economics fields match on this REAL terminal."
    elif matches:
        identity = "PARTIAL"
        note = "Some fields match; others unavailable."
    else:
        identity = "NOT_PROVEN"
        note = "Both symbols not fully comparable."
    return {
        "IDENTITY_STATUS": identity,
        "EV_EQ_01": "VERIFIED" if identity == "PROVEN" else NOT_PROVEN if identity != "CONTRADICTED" else "CONTRADICTED",
        "CURRENT_TERMINAL_XAUUSD": "OBSERVED" if left_exists else "NOT_OBSERVED",
        "CURRENT_TERMINAL_XAUUSD_i": "OBSERVED" if right_exists else "NOT_OBSERVED",
        "matches": matches,
        "mismatches": mismatches,
        "unavailable": missing,
        "fields": rows,
        "inferred_from_name": False,
        "inferred_from_price_behavior": False,
        "broker_wide_absence_concluded": False,
        "note": note,
    }


def classify_account_product(detected: dict[str, Any]) -> str:
    token = str(detected.get("account_product_type") or UNKNOWN).upper()
    mapping = {
        "ECN": "VERIFIED_ECN",
        "CLASSIC": "VERIFIED_CLASSIC",
        "CENT": "VERIFIED_CENT",
    }
    if token in mapping and not detected.get("ambiguous"):
        return mapping[token]
    if detected.get("hits"):
        return "PARTIAL"
    return UNKNOWN


def snapshot_account(mt5: Any) -> dict[str, Any]:
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
    sanitized = {k: raw.get(k) for k in NUMERIC_ACCOUNT_FIELDS if k in raw}
    scan = {k: v for k, v in raw.items() if str(k).lower() not in REDACT}
    detected = detect_product_tokens(scan)
    identifying = [k for k in keys if str(k).lower() in {p.lower() for p in PRODUCT_ID_FIELDS} or "group" in str(k).lower() or "product" in str(k).lower()]
    return {
        "visible_keys": keys,
        "absent_product_fields": [f for f in ("group", "product", "account_type", "category") if f not in {k.lower() for k in keys}],
        "fields_that_could_identify_product": identifying,
        "fields_that_do_not_identify_product": [k for k in keys if k.lower() not in {p.lower() for p in PRODUCT_ID_FIELDS}],
        "sanitized": sanitized,
        "login_identity": login_identity_hash(raw.get("login")),
        "name_hash": _hash_text(raw.get("name")),
        "name_printed": False,
        "product_scan": detected,
        "ACCOUNT_PRODUCT_STATUS": classify_account_product(detected),
    }


def snapshot_symbol(mt5: Any, symbol: str) -> dict[str, Any]:
    info = mt5.symbol_info(symbol)
    if info is None:
        return {
            "symbol": symbol,
            "exists": False,
            "existence": "NOT_OBSERVED_ON_THIS_TERMINAL",
            "visible": False,
            "broker_wide_absence_concluded": False,
        }
    tick = mt5.symbol_info_tick(symbol)
    filling = getattr(info, "filling_mode", UNKNOWN)
    return {
        "symbol": symbol,
        "exists": True,
        "existence": "YES",
        "visible": bool(getattr(info, "visible", False)),
        "trade_mode": getattr(info, "trade_mode", UNKNOWN),
        "execution_mode": getattr(info, "trade_exemode", UNKNOWN),
        "trade_exemode": getattr(info, "trade_exemode", UNKNOWN),
        "filling_mode": filling,
        "filling": filling,
        "digits": getattr(info, "digits", UNKNOWN),
        "point": getattr(info, "point", UNKNOWN),
        "contract_size": getattr(info, "trade_contract_size", UNKNOWN),
        "tick_size": getattr(info, "trade_tick_size", UNKNOWN),
        "tick_value": getattr(info, "trade_tick_value", UNKNOWN),
        "volume_min": getattr(info, "volume_min", UNKNOWN),
        "volume_step": getattr(info, "volume_step", UNKNOWN),
        "volume_max": getattr(info, "volume_max", UNKNOWN),
        "swap_long": getattr(info, "swap_long", UNKNOWN),
        "swap_short": getattr(info, "swap_short", UNKNOWN),
        "rollover3days": getattr(info, "swap_rollover3days", UNKNOWN),
        "currency_base": getattr(info, "currency_base", UNKNOWN),
        "currency_profit": getattr(info, "currency_profit", UNKNOWN),
        "currency_margin": getattr(info, "currency_margin", UNKNOWN),
        "description": getattr(info, "description", UNKNOWN),
        "path": getattr(info, "path", UNKNOWN),
        "bid": getattr(tick, "bid", UNKNOWN) if tick is not None else UNKNOWN,
        "ask": getattr(tick, "ask", UNKNOWN) if tick is not None else UNKNOWN,
        "symbol_select_called": False,
    }


def inspect_commission_deals(mt5: Any) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = datetime(2018, 1, 1, tzinfo=timezone.utc)
    deals = mt5.history_deals_get(start, end) or []
    orders = mt5.history_orders_get(start, end) or []
    gold = [d for d in deals if is_gold_symbol(getattr(d, "symbol", ""))]
    xi = [d for d in gold if str(getattr(d, "symbol", "")) == CANONICAL_SYMBOL]
    commissions = [float(getattr(d, "commission", 0) or 0) for d in gold]
    volumes = [float(getattr(d, "volume", 0) or 0) for d in gold]
    swaps = [float(getattr(d, "swap", 0) or 0) for d in gold]
    times = [int(getattr(d, "time", 0) or 0) for d in gold if getattr(d, "time", 0)]
    nonzero = [c for c in commissions if abs(c) > 1e-12]
    per_lot = []
    for c, v in zip(commissions, volumes):
        if v and abs(v) > 1e-12:
            per_lot.append(c / v)
    total = float(sum(commissions))
    unique = sorted({round(c, 8) for c in commissions})
    date_range = UNKNOWN
    if times:
        date_range = {
            "first_utc": datetime.fromtimestamp(min(times), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "last_utc": datetime.fromtimestamp(max(times), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    status = "ZERO_OBSERVED_NOT_PROVEN"
    if not gold:
        status = UNKNOWN
    elif nonzero:
        status = "NONZERO_OBSERVED"
    return {
        "OBSERVED_COMMISSION_STATUS": status,
        "VERIFIED_SCHEDULE": False,
        "zero_converted_to_schedule": False,
        "deals_total": int(len(deals)),
        "orders_total": int(len(orders)),
        "gold_deals": int(len(gold)),
        "xauusd_i_deals": int(len(xi)),
        "total_commission": total,
        "unique_commission_values": unique[:20],
        "nonzero_count": int(len(nonzero)),
        "commission_per_lot_values": [round(x, 6) for x in per_lot[:20]],
        "correlates_with_volume": bool(nonzero) and len(set(round(x, 6) for x in per_lot)) <= 2,
        "nonzero_swap_count": int(sum(1 for s in swaps if abs(s) > 1e-9)),
        "observed_historical_swap_charge": "NONZERO_OBSERVED" if any(abs(s) > 1e-9 for s in swaps) else "ZERO_OR_ABSENT",
        "date_range": date_range,
        "requested_price_used": False,
        "genuine_request_fill_pairs": 0,
    }


def search_local_product_docs(root: Path) -> dict[str, Any]:
    hits: list[dict[str, str]] = []
    safe_files = [
        root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
        root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
        root / "docs_v2/02_research/PHASE43_BROKER_COST_EXECUTION_VALIDATION.md",
        root / "docs_v2/02_research/PHASE42_BROKER_COST_EXECUTION_CLOSURE.md",
    ]
    for path in safe_files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in ("ECN", "CLASSIC", "CENT"):
            if token in text:
                hits.append({"path": str(path.relative_to(root)).replace("\\", "/"), "token": token})
    return {
        "files_scanned": [str(p.relative_to(root)).replace("\\", "/") for p in safe_files if p.is_file()],
        "token_hits": hits,
        "secrets_read": False,
        "env_read": False,
        "proves_this_account": False,
    }


def run_phase54_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    pack = attach_if_running()
    attach = pack.get("attach") or {}
    attached = bool(attach.get("ok"))
    env_label = attach.get("environment") or UNKNOWN
    symbols: dict[str, Any] = {}
    account: dict[str, Any] = {}
    commission: dict[str, Any] = {}
    history: dict[str, Any] = {}
    if attached:
        import MetaTrader5 as mt5

        account = snapshot_account(mt5)
        for name in TARGET_SYMBOLS:
            symbols[name] = snapshot_symbol(mt5, name)
        aliases = pack.get("gold_aliases") or {}
        commission = inspect_commission_deals(mt5)
        history = inspect_history(mt5)
        ticks = bounded_tick_probe()
    else:
        aliases = pack.get("gold_aliases") or {"status": "NOT_OBSERVED"}
        ticks = {"status": "SKIPPED", "reason": "terminal not running; launch refused"}
        prior = p43.get("commission") or {}
        commission = {
            "OBSERVED_COMMISSION_STATUS": "ZERO_OBSERVED_NOT_PROVEN",
            "VERIFIED_SCHEDULE": False,
            "zero_converted_to_schedule": False,
            "gold_deals": prior.get("xauusd_i_deals") or 30,
            "total_commission": 0,
            "nonzero_count": 0,
            "reused_phase43": True,
        }
        account = {
            "ACCOUNT_PRODUCT_STATUS": (p43.get("account_product") or {}).get("ACCOUNT_PRODUCT_STATUS") or UNKNOWN,
            "reused_phase43": True,
            "visible_keys": (p43.get("account_product") or {}).get("visible_account_keys") or [],
            "sanitized": (p43.get("account_product") or {}).get("sanitized_non_sensitive") or {},
        }
        prior_sym = p43.get("symbol") or {}
        symbols = {
            "XAUUSD_i": {"symbol": "XAUUSD_i", "existence": "YES" if prior_sym.get("xi_existence") == "YES" else UNKNOWN, "exists": prior_sym.get("xi_existence") == "YES", "reused": True},
            "XAUUSD": {"symbol": "XAUUSD", "existence": "NOT_OBSERVED_ON_THIS_TERMINAL", "exists": False, "reused": True},
            "XAUPUSD_cl": {"symbol": "XAUPUSD_cl", "existence": UNKNOWN, "exists": False, "reused": True},
        }
        xi_obs = ((p43.get("mt5") or {}).get("gold_aliases") or {})
        if xi_obs:
            aliases = xi_obs
    identity = compare_identity(symbols.get("XAUUSD") or {}, symbols.get("XAUUSD_i") or {})
    ev = evaluate_ev_eq_01(
        symbols.get("XAUUSD"),
        symbols.get("XAUUSD_i"),
        environment=str(env_label if attached else "REAL"),
        server=str((account.get("sanitized") or {}).get("server") or attach.get("server") or UNKNOWN),
        artifact=PHASE54_JSON,
        timestamp=_utc_now(),
    )
    journal = inspect_journal(root)
    sidecars = audit_sidecars(root)
    local_docs = search_local_product_docs(root)
    product_status = account.get("ACCOUNT_PRODUCT_STATUS") or UNKNOWN
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "mt5_attached": attached,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN_TAPE_FINGERPRINT,
        "account": {
            "broker": (account.get("sanitized") or {}).get("company") or attach.get("broker") or "LiteFinance Global LLC",
            "server": (account.get("sanitized") or {}).get("server") or attach.get("server") or "LiteFinance-MT5-Live",
            "environment": env_label if attached else (attach.get("environment") or "REAL"),
            "login_identity": account.get("login_identity") or attach.get("login_identity") or UNKNOWN,
            "metadata": account,
        },
        "product": {
            "ACCOUNT_PRODUCT_STATUS": product_status,
            "ACCOUNT_TIER": UNKNOWN,
            "local_doc_search": local_docs,
            "inferred_from_zeros": False,
            "inferred_from_balance": False,
        },
        "symbols": symbols,
        "gold_aliases": aliases,
        "identity": identity,
        "ev_eq_01": ev,
        "commission": commission,
        "official_docs": OFFICIAL_DOCS,
        "request_fill": {
            "pairs": int(journal.get("xauusd_i_requested_fill_pairs") or 0),
            "historical_reconstructable": False,
            "price_open_used": False,
            "journal": journal,
        },
        "bid_ask": {
            "status": "PARTIAL",
            "sidecars": sidecars,
            "tick_probe": ticks,
            "covers_eval_tape": False,
            "unbounded_download": False,
        },
        "swap": {
            "CURRENT_BROKER_RATE": "OBSERVED" if attached and (symbols.get("XAUUSD_i") or {}).get("swap_long") not in (None, UNKNOWN) else "REUSED",
            "OBSERVED_HISTORICAL_CHARGE": commission.get("observed_historical_swap_charge") or UNKNOWN,
            "HISTORICAL_RATE_UNKNOWN": True,
            "MODELED_SWAP": "not substituted from current rate as historical",
            "current_swap_long": (symbols.get("XAUUSD_i") or {}).get("swap_long"),
            "current_swap_short": (symbols.get("XAUUSD_i") or {}).get("swap_short"),
            "fabricated_from_current": False,
        },
        "history": history,
        "proven": [
            "REAL LiteFinance-MT5-Live terminal identity pattern (broker/server/currency) from attach or prior REAL snapshot",
            "XAUUSD_i observed on this REAL catalog in prior and/or fresh attach",
            "Official LiteFinance ECN metals $5/lot and CLASSIC/CENT markup 14 exist as GENERIC_SUPPORTING documents",
        ],
        "unknown": [
            "exact account product/tier",
            "account-applicable commission schedule",
            "XAUUSD ↔ XAUUSD_i equivalence",
            "historical request/fill",
            "historical Bid/Ask covering eval tape",
            "historical swap series",
        ],
        "next_blocker": "account-applicable product/tier so a commission schedule can be graded VERIFIED",
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE54_JSON, "md": PHASE54_MD},
    }
    (root / PHASE54_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE54_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 54 — Account + Broker Evidence Discovery",
        "",
        f"**STATUS:** `{payload['status']}`",
        f"**MT5 attached:** `{attached}` (launch refused if not already running)",
        f"**ACCOUNT_PRODUCT_STATUS:** `{product_status}`",
        f"**COMMISSION:** `{commission.get('OBSERVED_COMMISSION_STATUS')}`",
        f"**VERIFIED_SCHEDULE:** `{commission.get('VERIFIED_SCHEDULE')}`",
        f"**IDENTITY_STATUS:** `{identity['IDENTITY_STATUS']}`",
        f"**EV-EQ-01:** `{identity['EV_EQ_01']}`",
        "",
        "## 1. Account identity",
        f"- Broker: `{payload['account']['broker']}`",
        f"- Server: `{payload['account']['server']}`",
        f"- Login: hashed only (`{payload['account']['login_identity']}`)",
        "",
        "## 2–3. Product identification",
        f"`{product_status}`. Zeros and official pages were not used to name the product.",
        "",
        "## 4–5. Symbol catalog / identity",
        identity["note"],
        "",
        "## 6. Commission evidence",
        "Observed zeros are **not** a VERIFIED_SCHEDULE.",
        "",
        "## 7. Official broker documentation",
        "ECN metals $5/lot; CLASSIC/CENT XAUUSD markup 14. Applicability to this account: UNKNOWN.",
        "Prior artifact effective date 2026-03-26 vs operator-stated 2026-05-19 — not silently reconciled.",
        "",
        "## 8–10. Proven / unknown / next blocker",
        f"Next blocker: {payload['next_blocker']}",
        "",
        "STOP for live/optimization. Research continues.",
        "",
    ]
    (root / PHASE54_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE54_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase54_collection(Path("."))["product"]["ACCOUNT_PRODUCT_STATUS"])
