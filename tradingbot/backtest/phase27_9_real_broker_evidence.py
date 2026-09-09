"""Phase 27.9 — one bounded REAL-terminal read-only evidence attach.

Does not start or restart MT5, call symbol_select, place orders, or read/write .env.
If the attached account is DEMO, Real-specific collection stops.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    SymbolSpecSnapshot,
    build_equivalence_audit,
)

PHASE279_JSON = "logs/phase27_9_real_broker_evidence.json"
PHASE279_MD = "docs_v2/01_truth/PHASE27_9_REAL_BROKER_EVIDENCE.md"
KNOWN_UNKNOWNS = "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
CANONICAL_SYMBOL = "XAUUSD_i"
SYMBOLS = ("XAUUSD_i", "XAUUSD")
BOUNDED_ATTACH_ATTEMPTS = 1

# Requested report names → MT5 symbol_info attributes.
SYMBOL_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("digits", "digits"),
    ("point", "point"),
    ("contract_size", "trade_contract_size"),
    ("tick_size", "trade_tick_size"),
    ("tick_value", "trade_tick_value"),
    ("tick_value_profit", "trade_tick_value_profit"),
    ("tick_value_loss", "trade_tick_value_loss"),
    ("volume_min", "volume_min"),
    ("volume_max", "volume_max"),
    ("volume_step", "volume_step"),
    ("stops_level", "trade_stops_level"),
    ("freeze_level", "trade_freeze_level"),
    ("filling_mode", "filling_mode"),
    ("execution_mode", "trade_exemode"),
    ("calc_mode", "trade_calc_mode"),
    ("swap_long", "swap_long"),
    ("swap_short", "swap_short"),
    ("rollover3days", "swap_rollover3days"),
)

UNKNOWN = "UNKNOWN"


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


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def login_identity_hash(login: Any) -> str:
    """Non-reversible identity token. Never returns the raw login."""
    if login is None or login == "" or login == 0:
        return UNKNOWN
    digest = hashlib.sha256(str(login).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def classify_session(attached: bool, environment: str) -> tuple[str, str]:
    """Return (evidence_status, real_symbol_collection). DEMO never becomes REAL."""
    if not attached:
        return "MT5_NOT_ATTACHED", "NOT_ATTEMPTED"
    if environment == "DEMO":
        return "DEMO_ATTACHED_NOT_REAL", "STOPPED_DEMO_ATTACHED"
    if environment == "REAL":
        return "REAL_COLLECTED", "COLLECTED"
    return "ATTACHED_ENVIRONMENT_UNKNOWN", "STOPPED_ENVIRONMENT_NOT_REAL"


def trade_mode_label(trade_mode: Any) -> str:
    if trade_mode is None or trade_mode == "":
        return UNKNOWN
    try:
        mode = int(trade_mode)
    except (TypeError, ValueError):
        return UNKNOWN
    if mode == 2:
        return "REAL"
    if mode == 0:
        return "DEMO"
    if mode == 1:
        return "CONTEST"
    return UNKNOWN


def terminal64_running() -> bool:
    """Detect a running terminal64.exe. Does not start or restart MT5."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        text = (out.stdout or "").lower()
        return "terminal64.exe" in text
    except (OSError, subprocess.TimeoutExpired):
        return False


def bounded_readonly_attach_once() -> dict[str, Any]:
    """Exactly one attach-only initialize if a terminal is already running."""
    attempt: dict[str, Any] = {
        "attempt_count": BOUNDED_ATTACH_ATTEMPTS,
        "attach_only": True,
        "mt5_started_by_script": False,
        "mt5_restarted_by_script": False,
        "symbol_select_called": False,
        "orders_sent": False,
        "env_file_read": False,
        "env_file_written": False,
        "ok": False,
        "method": "initialize attach-only to already-running terminal64; no credentials; no symbol_select",
        "error": None,
    }
    try:
        import MetaTrader5 as mt5
    except ImportError:
        attempt["error"] = "MetaTrader5 package not installed"
        return attempt

    if not terminal64_running():
        attempt["error"] = "terminal64.exe not running — attach skipped (MT5 was not started)"
        return attempt

    try:
        existing = mt5.terminal_info()
        if existing is not None and bool(getattr(existing, "connected", False)):
            attempt["ok"] = True
            attempt["method"] = "reuse already-connected session; no second initialize"
            return attempt
        initialized = bool(mt5.initialize())
        if not initialized:
            attempt["error"] = f"mt5.initialize attach failed: {mt5.last_error()}"
            return attempt
        attempt["ok"] = True
        return attempt
    except Exception as exc:
        attempt["error"] = str(exc)
        return attempt


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
        }
    mode = getattr(acct, "trade_mode", None)
    company = getattr(acct, "company", None)
    server = getattr(acct, "server", None)
    currency = getattr(acct, "currency", None)
    return {
        "login_identity": login_identity_hash(getattr(acct, "login", None)),
        "login_present": getattr(acct, "login", None) not in (None, "", 0),
        "trade_mode": mode if mode is not None else UNKNOWN,
        "trade_mode_label": trade_mode_label(mode),
        "broker": str(company) if company else UNKNOWN,
        "server": str(server) if server else UNKNOWN,
        "currency": str(currency) if currency else UNKNOWN,
    }


def terminal_build_snapshot(mt5: Any) -> dict[str, Any]:
    info = mt5.terminal_info()
    if info is None:
        return {"build": UNKNOWN, "connected": False, "name": UNKNOWN}
    build = getattr(info, "build", None)
    name = getattr(info, "name", None)
    return {
        "build": build if build is not None else UNKNOWN,
        "connected": bool(getattr(info, "connected", False)),
        "name": str(name) if name else UNKNOWN,
    }


def _attr_or_unknown(info: Any, attr: str) -> Any:
    if info is None or not hasattr(info, attr):
        return UNKNOWN
    val = getattr(info, attr)
    if val is None:
        return UNKNOWN
    return val


def inspect_symbol_readonly(mt5: Any, symbol: str) -> dict[str, Any]:
    """symbol_info / symbol_info_tick only. Never symbol_select."""
    info = mt5.symbol_info(symbol)
    exists = info is not None
    row: dict[str, Any] = {
        "symbol": symbol,
        "existence": "YES" if exists else "NO",
        "visibility": UNKNOWN,
    }
    for report_name, attr in SYMBOL_FIELD_MAP:
        row[report_name] = _attr_or_unknown(info, attr) if exists else UNKNOWN
    if exists:
        vis = getattr(info, "visible", None)
        row["visibility"] = "YES" if vis else "NO" if vis is not None else UNKNOWN
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            row["bid"] = UNKNOWN
            row["ask"] = UNKNOWN
            row["quote_utc"] = UNKNOWN
        else:
            row["bid"] = getattr(tick, "bid", UNKNOWN)
            row["ask"] = getattr(tick, "ask", UNKNOWN)
            ts = getattr(tick, "time", None)
            row["quote_utc"] = (
                datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if ts
                else UNKNOWN
            )
    else:
        row["bid"] = UNKNOWN
        row["ask"] = UNKNOWN
        row["quote_utc"] = UNKNOWN
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


def spec_for_equivalence(row: dict[str, Any]) -> dict[str, Any]:
    """Map report fields back to MT5-style keys for EV-EQ-01. UNKNOWN stays absent."""
    reverse = {report: attr for report, attr in SYMBOL_FIELD_MAP}
    spec: dict[str, Any] = {}
    for report, attr in reverse.items():
        val = row.get(report, UNKNOWN)
        if val != UNKNOWN:
            spec[attr] = val
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
    return payload


def _unknown_symbol_row(symbol: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": symbol,
        "existence": UNKNOWN,
        "visibility": UNKNOWN,
        "bid": UNKNOWN,
        "ask": UNKNOWN,
        "quote_utc": UNKNOWN,
    }
    for report_name, _attr in SYMBOL_FIELD_MAP:
        row[report_name] = UNKNOWN
    return row


def run_phase27_9_real_broker_evidence(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    attach = bounded_readonly_attach_once()

    account = {
        "login_identity": UNKNOWN,
        "login_present": False,
        "trade_mode": UNKNOWN,
        "trade_mode_label": UNKNOWN,
        "broker": UNKNOWN,
        "server": UNKNOWN,
        "currency": UNKNOWN,
    }
    terminal = {"build": UNKNOWN, "connected": False, "name": UNKNOWN}
    env = UNKNOWN
    symbols: dict[str, Any] = {sym: _unknown_symbol_row(sym) for sym in SYMBOLS}
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
        artifact=PHASE279_JSON,
        timestamp=timestamp,
    )

    mislabeled = env == "DEMO" and evidence_status == "REAL_COLLECTED"
    procedure_pass = (
        not mislabeled
        and not attach["mt5_started_by_script"]
        and not attach["symbol_select_called"]
        and not attach["env_file_read"]
        and attach["attempt_count"] == 1
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.9",
        "status": "PASS" if procedure_pass else "FAIL",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "canonical_symbol_policy": CANONICAL_SYMBOL,
        "evidence_status": evidence_status,
        "account": _sanitize(account),
        "terminal": _sanitize(terminal),
        "account_environment": env,
        "labeled_as_real": env == "REAL",
        "real_symbol_collection": real_collection,
        "catalog": catalog,
        "symbols": symbols if real_collection == "COLLECTED" else {sym: _unknown_symbol_row(sym) for sym in SYMBOLS},
        "ev_eq_01": ev_eq,
        "attach_attempt": attach,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
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
            "equivalence_inferred": False,
        },
        "deferred": ["Phase 27.15+ — not started"],
    }
    if mislabeled:
        payload["status"] = "FAIL"

    out = root / PHASE279_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    update_known_unknowns_if_warranted(root, payload)
    return payload


def run_phase27_9_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_9_real_broker_evidence(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    acct = payload["account"]
    term = payload["terminal"]
    ev = payload["ev_eq_01"]
    catalog = payload["catalog"]
    env = payload["account_environment"]
    rows = []
    for sym in SYMBOLS:
        rec = payload["symbols"][sym]
        rows.append(
            f"| `{sym}` | {rec['existence']} | {rec['visibility']} | {rec['digits']} | "
            f"{rec['point']} | {rec['contract_size']} | {rec['swap_long']} / {rec['swap_short']} / "
            f"{rec['rollover3days']} | {rec['bid']} / {rec['ask']} | {rec['quote_utc']} |"
        )
    md = f"""# Phase 27.9 — Fresh Real Broker Read-Only Evidence

**Status:** {payload['status']}  
**Evidence status:** `{payload['evidence_status']}`  
**Artifact:** `{PHASE279_JSON}`

## Safety

One bounded attach-only attempt. MT5 was **not** started or restarted. `symbol_select` was not called. No orders. No `.env` read/write. Credentials were not written.

## Account / terminal identity

| Field | Value |
|---|---|
| login identity | `{acct['login_identity']}` (hash only; raw login not stored) |
| trade mode | `{acct['trade_mode']}` → **{acct['trade_mode_label']}** |
| broker | `{acct['broker']}` |
| server | `{acct['server']}` |
| currency | `{acct['currency']}` |
| terminal build | `{term['build']}` |

Connected environment: **{env}**. Labeled REAL: `{payload['labeled_as_real']}`. Real-specific collection: `{payload['real_symbol_collection']}`.

If this session is DEMO, it is recorded as DEMO and Real collection stops.

## Catalog (read-only `symbols_get`)

Exact matches: `{catalog.get('exact_matches')}`. Total symbols: `{catalog.get('total_symbols')}`.

## Symbol snapshots

Unavailable fields are **UNKNOWN**. Equivalence is not inferred.

| Symbol | exists | visible | digits | point | contract | swap L/S/3d | bid/ask | UTC |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## EV-EQ-01

**{ev.get('status', 'NOT_PROVEN')}** — {ev.get('rationale', '')}

Canonical symbol policy remains `XAUUSD_i`. That policy does not prove `XAUUSD` ≡ `XAUUSD_i`.

## Production

**BLOCKED.** No RiskGate, strategy, or execution changes.

## Next

STOP after Phase 27.9.
"""
    (root / PHASE279_MD).write_text(md, encoding="utf-8")


def update_known_unknowns_if_warranted(root: Path, payload: dict[str, Any]) -> None:
    """Update only rows the fresh attach actually changes."""
    path = root / KNOWN_UNKNOWNS
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.9 Real evidence:** `{PHASE279_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.14 slippage model:** `logs/phase27_14_slippage_model.json`",
            f"**Phase 27.14 slippage model:** `logs/phase27_14_slippage_model.json`  \n{pointer}",
        )

    env = payload.get("account_environment")
    evidence = payload.get("evidence_status")
    date = str(payload.get("timestamp") or "")[:10]
    if evidence == "MT5_NOT_ATTACHED":
        text = text.replace(
            "| Fresh MT5 operator session | **DEFERRED** |",
            f"| Fresh MT5 operator session | **DEFERRED** — Phase 27.9 attach attempted {date}; terminal not connected (not started) |",
        )
    elif env == "DEMO":
        text = text.replace(
            "| Fresh MT5 operator session | **DEFERRED** |",
            f"| Fresh MT5 operator session | **DEMO attached {date}** — not labeled REAL; Real-specific collection stopped |",
        )
    elif env == "REAL" and evidence == "REAL_COLLECTED":
        text = text.replace(
            "| Fresh MT5 operator session | **DEFERRED** |",
            f"| Fresh MT5 operator session | **REAL attached {date}** — read-only; see Phase 27.9 |",
        )
        xau = payload["symbols"]["XAUUSD"]["existence"]
        xaui = payload["symbols"]["XAUUSD_i"]["existence"]
        if xau == "NO":
            text = text.replace(
                "| XAUUSD absent on observed Demo/Real LiteFinance terminals | **PROVEN** (STALE 2026-09-02) |",
                f"| XAUUSD absent on observed Demo/Real LiteFinance terminals | **PROVEN** (fresh Real {date}: existence=NO) |",
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
                f"| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN (Phase 27.9 Real re-evaluated {date}) |",
            )
        elif ev_status == EquivalenceConclusion.DISPROVEN.value:
            text = text.replace(
                "| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN |",
                f"| XAUUSD economically equivalent to XAUUSD_i | **DISPROVEN** (Phase 27.9 Real {date}) |",
            )
        elif ev_status == EquivalenceConclusion.PROVEN.value:
            text = text.replace(
                "| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN |",
                f"| XAUUSD economically equivalent to XAUUSD_i | **PROVEN** (Phase 27.9 Real {date}) |",
            )

    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
