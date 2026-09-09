"""Phase 27.17 — fresh Real LiteFinance-MT5-Live read-only evidence.

One bounded attach. Does not start/restart MT5, call symbol_select,
place orders, read/write .env, or overwrite stale Real artifacts.
Demo is never labeled Real.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.commission_policy import (
    POLICY as COMMISSION_POLICY,
    missing_applicability_fields,
    verified_schedule_requires_applicability,
)
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    UNKNOWN,
    bounded_readonly_attach_once,
    classify_session,
    login_identity_hash,
    trade_mode_label,
)
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    SymbolSpecSnapshot,
    build_equivalence_audit,
)

PHASE2717_JSON = "logs/phase27_17_real_broker_evidence.json"
PHASE2717_MD = "docs_v2/01_truth/PHASE27_17_REAL_BROKER_EVIDENCE.md"
STALE_REAL_JSON = "logs/operator_broker_evidence_raw.json"
PHASE2716_JSON = "logs/phase27_16_FINAL_VALIDATION_GATE.json"
KNOWN_UNKNOWNS = "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
CANONICAL_SYMBOL = "XAUUSD_i"
SYMBOLS = ("XAUUSD_i", "XAUUSD")

SYMBOL_FIELDS: tuple[str, ...] = (
    "digits",
    "point",
    "trade_contract_size",
    "trade_tick_size",
    "trade_tick_value",
    "trade_tick_value_profit",
    "trade_tick_value_loss",
    "volume_min",
    "volume_max",
    "volume_step",
    "trade_stops_level",
    "trade_freeze_level",
    "filling_mode",
    "trade_mode",
    "trade_exemode",
    "trade_calc_mode",
    "currency_base",
    "currency_profit",
    "currency_margin",
    "swap_long",
    "swap_short",
    "swap_rollover3days",
)

EQUIVALENCE_SPEC_KEYS = (
    "digits",
    "point",
    "trade_contract_size",
    "trade_tick_size",
    "trade_tick_value",
    "trade_tick_value_profit",
    "trade_tick_value_loss",
    "volume_min",
    "volume_max",
    "volume_step",
    "trade_stops_level",
    "trade_freeze_level",
    "trade_exemode",
    "trade_calc_mode",
    "currency_profit",
    "currency_margin",
    "swap_long",
    "swap_short",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    import subprocess

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


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        return UNKNOWN
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest[:16]}"


def _attr_or_unknown(info: Any, attr: str) -> Any:
    if info is None or not hasattr(info, attr):
        return UNKNOWN
    val = getattr(info, attr)
    return UNKNOWN if val is None else val


def unknown_symbol_row(symbol: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": symbol,
        "existence": UNKNOWN,
        "visibility": UNKNOWN,
        "bid": UNKNOWN,
        "ask": UNKNOWN,
        "spread": UNKNOWN,
        "spread_points": UNKNOWN,
        "utc_timestamp": UNKNOWN,
    }
    for field in SYMBOL_FIELDS:
        row[field] = UNKNOWN
    return row


def inspect_symbol_readonly(mt5: Any, symbol: str) -> dict[str, Any]:
    """symbol_info / symbol_info_tick only. Never symbol_select."""
    info = mt5.symbol_info(symbol)
    exists = info is not None
    row = unknown_symbol_row(symbol)
    row["existence"] = "YES" if exists else "NO"
    if not exists:
        return row
    vis = getattr(info, "visible", None)
    row["visibility"] = "YES" if vis else "NO" if vis is not None else UNKNOWN
    for field in SYMBOL_FIELDS:
        row[field] = _attr_or_unknown(info, field)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return row
    bid = getattr(tick, "bid", UNKNOWN)
    ask = getattr(tick, "ask", UNKNOWN)
    row["bid"] = bid
    row["ask"] = ask
    ts = getattr(tick, "time", None)
    row["utc_timestamp"] = (
        datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if ts
        else UNKNOWN
    )
    try:
        if bid != UNKNOWN and ask != UNKNOWN:
            row["spread"] = float(ask) - float(bid)
    except (TypeError, ValueError):
        row["spread"] = UNKNOWN
    spread_pts = getattr(info, "spread", None)
    row["spread_points"] = spread_pts if spread_pts is not None else UNKNOWN
    return row


def catalog_existence_check(mt5: Any, symbols: tuple[str, ...] = SYMBOLS) -> dict[str, Any]:
    names: set[str] = set()
    error = None
    try:
        all_symbols = mt5.symbols_get()
        if all_symbols:
            names = {str(s.name) for s in all_symbols}
    except Exception as exc:
        error = str(exc)
    return {
        "method": "symbols_get read-only",
        "total_symbols": len(names) if names else UNKNOWN if error else 0,
        "exact_matches": {sym: ("YES" if sym in names else "NO") for sym in symbols},
        "error": error,
    }


def account_identity_snapshot(mt5: Any) -> dict[str, Any]:
    acct = mt5.account_info()
    if acct is None:
        return {
            "login_identity": UNKNOWN,
            "login_present": False,
            "trade_mode": UNKNOWN,
            "trade_mode_label": UNKNOWN,
            "broker": UNKNOWN,
            "server": UNKNOWN,
            "currency": UNKNOWN,
            "leverage": UNKNOWN,
            "margin_mode": UNKNOWN,
            "account_product_type": UNKNOWN,
        }
    mode = getattr(acct, "trade_mode", None)
    return {
        "login_identity": login_identity_hash(getattr(acct, "login", None)),
        "login_present": getattr(acct, "login", None) not in (None, "", 0),
        "trade_mode": mode if mode is not None else UNKNOWN,
        "trade_mode_label": trade_mode_label(mode),
        "broker": str(getattr(acct, "company", None) or UNKNOWN),
        "server": str(getattr(acct, "server", None) or UNKNOWN),
        "currency": str(getattr(acct, "currency", None) or UNKNOWN),
        "leverage": getattr(acct, "leverage", UNKNOWN),
        "margin_mode": getattr(acct, "margin_mode", UNKNOWN),
        "account_product_type": UNKNOWN,
    }


def terminal_build_snapshot(mt5: Any) -> dict[str, Any]:
    info = mt5.terminal_info()
    if info is None:
        return {"build": UNKNOWN, "connected": False, "name": UNKNOWN}
    return {
        "build": getattr(info, "build", UNKNOWN),
        "connected": bool(getattr(info, "connected", False)),
        "name": str(getattr(info, "name", None) or UNKNOWN),
    }


def spec_for_equivalence(row: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    for key in EQUIVALENCE_SPEC_KEYS:
        val = row.get(key, UNKNOWN)
        if val != UNKNOWN:
            spec[key] = val
    return spec


def evaluate_ev_eq_01(
    xauusd: dict[str, Any] | None,
    xauusd_i: dict[str, Any] | None,
    *,
    environment: str,
    server: str,
    artifact: str,
    timestamp: str,
) -> dict[str, Any]:
    if environment != "REAL" or not xauusd or not xauusd_i:
        return {
            "id": "EV-EQ-01",
            "status": EquivalenceConclusion.NOT_PROVEN.value,
            "rationale": (
                "Real-terminal comparison not available"
                if environment != "REAL"
                else "both symbols were not collected"
            ),
            "inferred": False,
            "both_symbols_present": False,
            "similar_economics_not_sufficient": True,
        }
    left = SymbolSpecSnapshot(
        symbol="XAUUSD",
        exists=xauusd.get("existence") == "YES",
        visible=True if xauusd.get("visibility") == "YES" else False if xauusd.get("visibility") == "NO" else None,
        environment=environment,
        server=server,
        evidence_artifact=artifact,
        evidence_timestamp=timestamp,
        spec=spec_for_equivalence(xauusd),
    )
    right = SymbolSpecSnapshot(
        symbol="XAUUSD_i",
        exists=xauusd_i.get("existence") == "YES",
        visible=True if xauusd_i.get("visibility") == "YES" else False if xauusd_i.get("visibility") == "NO" else None,
        environment=environment,
        server=server,
        evidence_artifact=artifact,
        evidence_timestamp=timestamp,
        spec=spec_for_equivalence(xauusd_i),
    )
    audit = build_equivalence_audit(left, right, same_environment=True)
    payload = audit.to_dict()
    payload["id"] = "EV-EQ-01"
    payload["status"] = audit.ev_eq_01
    payload["inferred"] = False
    payload["both_symbols_present"] = bool(left.exists and right.exists)
    payload["similar_economics_not_sufficient"] = True
    payload["absence_not_broker_wide"] = xauusd.get("existence") == "NO"
    return payload


def commission_evidence_from_account(account: dict[str, Any], *, collected_real: bool) -> dict[str, Any]:
    candidate = {
        "broker": account.get("broker"),
        "server": account.get("server"),
        "account_type": account.get("trade_mode_label"),
        "asset_class": "gold" if collected_real else UNKNOWN,
        "symbol": CANONICAL_SYMBOL if collected_real else UNKNOWN,
        "basis": UNKNOWN,
        "currency": account.get("currency"),
        "effective_date_or_version": UNKNOWN,
        "applicability_established": False,
        "account_product_type": account.get("account_product_type") or UNKNOWN,
        "public_supporting_only": False,
    }
    missing = missing_applicability_fields(candidate)
    return {
        "policy": COMMISSION_POLICY,
        "status": "UNKNOWN",
        "verified_schedule_found": False,
        "verified_schedule_claimed": False,
        "public_documentation_used_as_verified": False,
        "applicability_established": verified_schedule_requires_applicability(candidate),
        "missing_applicability_fields": missing,
        "candidate": candidate,
        "note": (
            "Account identity is not a commission schedule. "
            "VERIFIED_SCHEDULE is not claimed."
        ),
    }


def stale_real_snapshot(root: Path) -> dict[str, Any]:
    data = _safe_load_json(root / STALE_REAL_JSON) or {}
    acct = data.get("account") if isinstance(data.get("account"), dict) else {}
    return {
        "artifact": STALE_REAL_JSON,
        "present": (root / STALE_REAL_JSON).is_file(),
        "collection_utc": data.get("collection_utc"),
        "server": acct.get("server"),
        "account_type": acct.get("type"),
        "sha256_16": _file_sha256(root / STALE_REAL_JSON),
        "overwritten": False,
    }


def operator_blocker_for(evidence_status: str) -> str:
    if evidence_status == "REAL_COLLECTED":
        return "NONE"
    return "BLOCKED_PENDING_OPERATOR"


def run_phase27_17_real_broker_evidence(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    stale_before = stale_real_snapshot(root)
    attach = bounded_readonly_attach_once()

    account = {
        "login_identity": UNKNOWN,
        "login_present": False,
        "trade_mode": UNKNOWN,
        "trade_mode_label": UNKNOWN,
        "broker": UNKNOWN,
        "server": UNKNOWN,
        "currency": UNKNOWN,
        "leverage": UNKNOWN,
        "margin_mode": UNKNOWN,
        "account_product_type": UNKNOWN,
    }
    terminal = {"build": UNKNOWN, "connected": False, "name": UNKNOWN}
    env = UNKNOWN
    symbols = {sym: unknown_symbol_row(sym) for sym in SYMBOLS}
    catalog = {
        "method": "symbols_get read-only",
        "total_symbols": UNKNOWN,
        "exact_matches": {sym: UNKNOWN for sym in SYMBOLS},
        "error": None,
    }
    real_collection = "NOT_ATTEMPTED"
    evidence_status = "MT5_NOT_ATTACHED"

    if attach["ok"]:
        import MetaTrader5 as mt5

        account = account_identity_snapshot(mt5)
        terminal = terminal_build_snapshot(mt5)
        env = str(account.get("trade_mode_label") or UNKNOWN)
        evidence_status, real_collection = classify_session(True, env)
        if real_collection == "COLLECTED":
            catalog = catalog_existence_check(mt5)
            symbols = {sym: inspect_symbol_readonly(mt5, sym) for sym in SYMBOLS}

    ev_eq = evaluate_ev_eq_01(
        symbols.get("XAUUSD") if real_collection == "COLLECTED" else None,
        symbols.get("XAUUSD_i") if real_collection == "COLLECTED" else None,
        environment=env if env == "REAL" else "NOT_REAL",
        server=str(account.get("server") or UNKNOWN),
        artifact=PHASE2717_JSON,
        timestamp=timestamp,
    )
    commission = commission_evidence_from_account(account, collected_real=real_collection == "COLLECTED")

    stale_after = stale_real_snapshot(root)
    stale_untouched = stale_before["sha256_16"] == stale_after["sha256_16"]
    mislabeled = env == "DEMO" and (evidence_status == "REAL_COLLECTED" or real_collection == "COLLECTED")
    demo_used_as_real = env == "DEMO" and bool(real_collection == "COLLECTED")

    session_class = "NOT_COLLECTED"
    if evidence_status == "MT5_NOT_ATTACHED":
        session_class = "NOT_COLLECTED"
    elif env == "DEMO":
        session_class = "DEMO_NOT_REAL"
    elif env == "REAL" and real_collection == "COLLECTED":
        session_class = "FRESH_REAL"

    final_gate = UNKNOWN
    p16 = _safe_load_json(root / PHASE2716_JSON) or {}
    if p16:
        final_gate = p16.get("FINAL_GATE") or p16.get("final_gate") or UNKNOWN

    procedure_pass = (
        not mislabeled
        and not demo_used_as_real
        and stale_untouched
        and not attach["mt5_started_by_script"]
        and not attach["symbol_select_called"]
        and not attach["env_file_read"]
        and attach["attempt_count"] == 1
        and not commission["verified_schedule_claimed"]
        and ev_eq.get("inferred") is False
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.17",
        "status": "PASS" if procedure_pass else "FAIL",
        "timestamp": timestamp,
        "fresh_timestamp": timestamp,
        "repository_commit": _git_head(root),
        "canonical_symbol_policy": CANONICAL_SYMBOL,
        "operator_policy": dict(LOCKED_POLICY),
        "attach_status": evidence_status,
        "evidence_status": evidence_status,
        "operator_blocker": operator_blocker_for(evidence_status),
        "account_environment": env,
        "broker": account.get("broker"),
        "server": account.get("server"),
        "terminal_build": terminal.get("build"),
        "account": _sanitize(account),
        "terminal": _sanitize(terminal),
        "labeled_as_real": env == "REAL",
        "real_symbol_collection": real_collection,
        "catalog": catalog,
        "XAUUSD_status": {
            "existence": symbols["XAUUSD"]["existence"],
            "visibility": symbols["XAUUSD"]["visibility"],
            "catalog": (catalog.get("exact_matches") or {}).get("XAUUSD", UNKNOWN),
            "absence_not_broker_wide": True,
        },
        "XAUUSD_i_status": {
            "existence": symbols["XAUUSD_i"]["existence"],
            "visibility": symbols["XAUUSD_i"]["visibility"],
            "catalog": (catalog.get("exact_matches") or {}).get("XAUUSD_i", UNKNOWN),
            "canonical_symbol_evidence": symbols["XAUUSD_i"]["existence"] == "YES",
        },
        "symbols": symbols if real_collection == "COLLECTED" else {sym: unknown_symbol_row(sym) for sym in SYMBOLS},
        "economics": {
            "XAUUSD": symbols["XAUUSD"] if real_collection == "COLLECTED" else unknown_symbol_row("XAUUSD"),
            "XAUUSD_i": symbols["XAUUSD_i"] if real_collection == "COLLECTED" else unknown_symbol_row("XAUUSD_i"),
            "class": session_class,
        },
        "ev_eq_01": ev_eq,
        "commission_evidence_status": commission,
        "stale_vs_fresh": {
            "stale_real": stale_after,
            "this_session_class": session_class,
            "demo_used_as_real": demo_used_as_real,
            "stale_real_overwritten": not stale_untouched,
            "stale_real_artifact_untouched": stale_untouched,
        },
        "attach_attempt": attach,
        "phase27_16_final_gate_unchanged": final_gate,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_actions_performed": [
            "tasklist check for terminal64.exe",
            "at most one attach-only initialize if terminal already running",
            "read-only account_info / terminal_info when attached",
            "read-only symbol_info / symbol_info_tick / symbols_get only if REAL",
        ],
        "safety_actions_not_performed": [
            "start MT5",
            "restart MT5",
            "symbol_select",
            "order_send / place orders",
            "account state modification",
            ".env read",
            ".env write",
            "credential exposure",
            "overwrite stale Real artifact",
            "label DEMO as REAL",
            "claim VERIFIED_SCHEDULE",
            "infer EV-EQ-01 from similar economics",
            "infer broker-wide XAUUSD absence",
            "start Phase 27.18+",
        ],
        "safety_confirmation": {
            "mt5_started": False,
            "mt5_restarted": False,
            "symbol_select_called": False,
            "orders_sent": False,
            "account_state_modified": False,
            "env_file_read": False,
            "env_file_written": False,
            "credentials_exposed": False,
            "demo_mislabeled_as_real": bool(mislabeled),
            "stale_real_overwritten": not stale_untouched,
            "equivalence_inferred": False,
            "verified_schedule_claimed": False,
            "phase_27_18_started": False,
        },
        "deferred": ["Phase 27.18+ — not started"],
    }
    if mislabeled or demo_used_as_real or not stale_untouched:
        payload["status"] = "FAIL"

    out = root / PHASE2717_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    update_known_unknowns_if_warranted(root, payload)
    return payload


def run_phase27_17_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_17_real_broker_evidence(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    acct = payload["account"]
    term = payload["terminal"]
    ev = payload["ev_eq_01"]
    comm = payload["commission_evidence_status"]
    stale = payload["stale_vs_fresh"]
    xau = payload["XAUUSD_status"]
    xaui = payload["XAUUSD_i_status"]
    rows = []
    for sym in SYMBOLS:
        rec = payload["symbols"][sym]
        rows.append(
            f"| `{sym}` | {rec['existence']} | {rec['visibility']} | {rec['digits']} | "
            f"{rec['point']} | {rec['trade_contract_size']} | {rec['swap_long']} / {rec['swap_short']} / "
            f"{rec['swap_rollover3days']} | {rec['bid']} / {rec['ask']} | {rec['utc_timestamp']} |"
        )
    md = f"""# Phase 27.17 — Fresh Real Broker Evidence Closure

**Status:** {payload['status']} (procedure)  
**Attach status:** `{payload['attach_status']}`  
**Operator blocker:** `{payload['operator_blocker']}`  
**Artifact:** `{PHASE2717_JSON}`

Phase 27.16 **FINAL_GATE remains `{payload['phase27_16_final_gate_unchanged']}`**. This phase does not weaken that gate.

## Safety

One bounded attach-only attempt. MT5 was **not** started or restarted. `symbol_select` was not called. No orders. No `.env` read/write. Credentials were not written. Stale Real artifact was **not** overwritten.

## Account / terminal

| Field | Value |
|---|---|
| environment | **{payload['account_environment']}** |
| trade mode | `{acct['trade_mode']}` → `{acct['trade_mode_label']}` |
| broker | `{payload['broker']}` |
| server | `{payload['server']}` |
| currency | `{acct['currency']}` |
| terminal build | `{payload['terminal_build']}` |
| connected | `{term['connected']}` |
| labeled REAL | `{payload['labeled_as_real']}` |
| Real collection | `{payload['real_symbol_collection']}` |
| fresh timestamp | `{payload['fresh_timestamp']}` |

If this session is DEMO, it is recorded as DEMO. Real-specific collection stops. Demo is not written over stale Real evidence.

## Catalog

Exact matches: `{payload['catalog'].get('exact_matches')}`. Total symbols: `{payload['catalog'].get('total_symbols')}`.

## Symbol status

| Symbol | existence | visibility | catalog | note |
|---|---|---|---|---|
| XAUUSD | `{xau['existence']}` | `{xau['visibility']}` | `{xau['catalog']}` | absence is not broker-wide |
| XAUUSD_i | `{xaui['existence']}` | `{xaui['visibility']}` | `{xaui['catalog']}` | canonical-symbol evidence only if YES |

| Symbol | exists | visible | digits | point | contract | swap L/S/3d | bid/ask | UTC |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## EV-EQ-01

**{ev.get('status', 'NOT_PROVEN')}** — {ev.get('rationale', '')}

Similar economics do **not** prove `XAUUSD` ≡ `XAUUSD_i`. The project equivalence contract was used; no inference shortcut.

## Commission

Policy remains `{comm['policy']}`. Verified schedule found: **{comm['verified_schedule_found']}**.  
Missing applicability: `{comm['missing_applicability_fields']}`. Public docs were not treated as account-specific.

## Stale vs fresh

| Field | Value |
|---|---|
| stale Real artifact | `{stale['stale_real']['artifact']}` |
| stale timestamp | `{stale['stale_real']['collection_utc']}` |
| this session | `{stale['this_session_class']}` |
| stale overwritten | **{stale['stale_real_overwritten']}** |
| Demo used as Real | **{stale['demo_used_as_real']}** |

## Production

**BLOCKED.** No Strategy, RiskGate, execution, sizing, or RR changes. Phase 27.18+ not started.

## Next

STOP after Phase 27.17.
"""
    (root / PHASE2717_MD).write_text(md, encoding="utf-8")


def update_known_unknowns_if_warranted(root: Path, payload: dict[str, Any]) -> None:
    path = root / KNOWN_UNKNOWNS
    if not path.is_file():
        return
    original = path.read_text(encoding="utf-8")
    text = original
    pointer = f"**Phase 27.17 Real evidence:** `{PHASE2717_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.16 final validation gate:** `logs/phase27_16_FINAL_VALIDATION_GATE.json` — **FINAL_GATE=BLOCKED**",
            "**Phase 27.16 final validation gate:** `logs/phase27_16_FINAL_VALIDATION_GATE.json` — **FINAL_GATE=BLOCKED**  \n"
            f"{pointer}",
        )

    env = payload.get("account_environment")
    evidence = payload.get("evidence_status")
    date = str(payload.get("fresh_timestamp") or "")[:10]
    fresh_row_old = (
        "| Fresh MT5 operator session | **DEFERRED** — Phase 27.9 attach attempted 2026-09-06; "
        "terminal not connected (not started) |"
    )
    if evidence == "MT5_NOT_ATTACHED":
        text = text.replace(
            fresh_row_old,
            f"| Fresh MT5 operator session | **DEFERRED** — Phase 27.17 attach attempted {date}; "
            "terminal not connected (not started); Real blocker remains BLOCKED_PENDING_OPERATOR |",
        )
    elif env == "DEMO":
        text = text.replace(
            fresh_row_old,
            f"| Fresh MT5 operator session | **DEMO attached {date}** — not labeled REAL; "
            "stale Real artifact untouched; Real blocker remains open |",
        )
    elif env == "REAL" and evidence == "REAL_COLLECTED":
        text = text.replace(
            fresh_row_old,
            f"| Fresh MT5 operator session | **REAL attached {date}** — read-only; see Phase 27.17 |",
        )
        xau = payload["XAUUSD_status"]["existence"]
        xaui = payload["XAUUSD_i_status"]["existence"]
        if xau == "NO":
            text = text.replace(
                "| XAUUSD absent on observed Demo/Real LiteFinance terminals | **PROVEN** (STALE 2026-09-02) |",
                f"| XAUUSD absent on observed Demo/Real LiteFinance terminals | **PROVEN** (fresh Real {date}: existence=NO; not broker-wide) |",
            )
        elif xau == "YES":
            text = text.replace(
                "| XAUUSD absent on observed Demo/Real LiteFinance terminals | **PROVEN** (STALE 2026-09-02) |",
                f"| XAUUSD absent on observed Demo/Real LiteFinance terminals | **SUPERSEDED** — XAUUSD existence=YES on Real {date}; EV-EQ-01 still separate |",
            )
        if xaui == "YES":
            text = text.replace(
                "| XAUUSD_i present on observed terminals | **PROVEN** (STALE 2026-09-02) |",
                f"| XAUUSD_i present on observed terminals | **PROVEN** (fresh Real {date}: existence=YES) |",
            )
        ev_status = payload["ev_eq_01"].get("status")
        if ev_status == EquivalenceConclusion.NOT_PROVEN.value:
            text = text.replace(
                "| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN |",
                f"| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN (Phase 27.17 Real re-evaluated {date}) |",
            )
        elif ev_status == EquivalenceConclusion.DISPROVEN.value:
            text = text.replace(
                "| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN |",
                f"| XAUUSD economically equivalent to XAUUSD_i | **DISPROVEN** (Phase 27.17 Real {date}) |",
            )
        elif ev_status == EquivalenceConclusion.PROVEN.value:
            text = text.replace(
                "| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN |",
                f"| XAUUSD economically equivalent to XAUUSD_i | **PROVEN** (Phase 27.17 Real {date}; project equivalence contract) |",
            )

    if text != original:
        path.write_text(text, encoding="utf-8")
