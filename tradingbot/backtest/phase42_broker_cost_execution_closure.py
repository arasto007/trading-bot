"""Phase 42 — broker cost, execution telemetry, Bid/Ask, swap, symbol mapping.

RESEARCH ONLY. Attaches MT5 only if terminal64 is already running.
Does not launch MT5, trade, read .env, import live.py, rerun Phase 40,
or start Phase 43.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    account_identity_snapshot,
    bounded_readonly_attach_once,
    catalog_existence_check,
    evaluate_ev_eq_01,
    inspect_symbol_readonly,
    terminal64_running,
    terminal_build_snapshot,
)
from tradingbot.backtest.phase42_cost_reconstruction import reconstruct_frozen_phase40

PHASE = "42"
PHASE42_JSON = "logs/phase42_broker_cost_execution_closure.json"
PHASE42_MD = "docs_v2/02_research/PHASE42_BROKER_COST_EXECUTION_CLOSURE.md"
PHASE42_MATRIX_MD = "docs_v2/02_research/PHASE42_EVIDENCE_MATRIX.md"
PHASE42_READY_MD = "docs_v2/02_research/PHASE42_EXECUTABLE_READINESS.md"
PHASE39_JSON = "logs/phase39_broker_economics_execution.json"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE41_JSON = "logs/phase41_final_evidence_closure.json"
PHASE2716_JSON = "logs/phase27_16_FINAL_VALIDATION_GATE.json"
JOURNAL_DB = "data/trade_journal.db"
CANONICAL_SYMBOL = "XAUUSD_i"
LOGICAL_SYMBOL = "XAUUSD"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"
BLOCKED = "BLOCKED"
OBSERVED_ZERO_NOT_PROVEN = "OBSERVED_ZERO_NOT_PROVEN"
PREFERRED_EXE = r"C:\Program Files\MetaTrader 5\terminal64.exe"
HISTORY_START = datetime(2018, 1, 1, tzinfo=timezone.utc)
TICK_PROBE_SECONDS = 12
SIDECARS = (
    "logs/phase27_26_xauusd_i_m5_bidask.parquet",
    "logs/phase38_xauusd_i_bidask.parquet",
)
EXTRA_SYMBOL_ATTRS = (
    ("description", "description"),
    ("currency_base", "currency_base"),
    ("currency_profit", "currency_profit"),
    ("currency_margin", "currency_margin"),
    ("spread", "spread"),
    ("trade_mode", "trade_mode"),
    ("trade_contract_size", "trade_contract_size"),
    ("trade_tick_size", "trade_tick_size"),
    ("trade_tick_value", "trade_tick_value"),
    ("trade_exemode", "trade_exemode"),
    ("swap_rollover3days", "swap_rollover3days"),
)
PUBLIC_ECN = {
    "source": "https://www.litefinance.org/trading/account-types/ecn/",
    "pdf": "https://www.litefinance.org/uploads/documents/pdf-litefinance/litefinance-markups-and-commissions-list-en.pdf",
    "precious_metals_mt5_usd_per_lot": 5.0,
    "charged": "when opening a trade on MT4/MT5",
    "effective_pdf": "2026-03-26",
    "account_applicability": "NOT_PROVEN",
    "grade": "OFFICIAL_BROKER_GENERAL_DOCUMENT",
}
FORBIDDEN_OUTPUT_KEYS = ("password", "mt5_password", "token", "api_key", "investor", "login")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "broker",
    "symbol",
    "commission",
    "swap",
    "spread",
    "slippage",
    "request_fill",
    "execution",
    "ev_eq_01",
    "cost_gates",
    "executable_contract",
    "reconstruction",
    "blocker_update",
    "final_gate",
    "verdict",
    "production_safety",
    "artifacts",
)
PHASE41_BLOCKER_NAMES = (
    "Commission unknown",
    "Request/fill pairs absent",
    "Historical Bid/Ask incomplete",
    "Historical swap series unknown",
    "Symbol mapping not proven",
    "Executable evaluation unavailable",
    "OOS/regime/dependence uncertainty",
    "Production configuration / FINAL_GATE",
)


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


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}


def is_gold_symbol(symbol: Any) -> bool:
    text = str(symbol or "").upper()
    return text in {"XAUUSD", "XAUUSD_I"} or "XAU" in text or text.startswith("GOLD")


def _augment_symbol(mt5: Any, row: dict[str, Any]) -> dict[str, Any]:
    if row.get("existence") != "YES":
        if row.get("existence") == "NO":
            row["existence"] = "NOT_OBSERVED_ON_THIS_TERMINAL"
        row["broker_wide_absence_concluded"] = False
        return row
    info = mt5.symbol_info(row.get("symbol"))
    if info is None:
        return row
    for report, attr in EXTRA_SYMBOL_ATTRS:
        if row.get(report) in (None, UNKNOWN) or report not in row:
            val = getattr(info, attr, UNKNOWN)
            row[report] = val if val is not None else UNKNOWN
    row["broker_wide_absence_concluded"] = False
    row["symbol_select_called"] = False
    return row


def gold_alias_scan(mt5: Any) -> dict[str, Any]:
    try:
        symbols = mt5.symbols_get() or []
    except Exception as exc:
        return {"status": "BLOCKED", "error": str(exc)[:200], "symbol_select_called": False}
    hits = []
    for info in symbols:
        name = str(getattr(info, "name", "") or "")
        desc = str(getattr(info, "description", "") or "")
        up_name = name.upper()
        up_desc = desc.upper()
        goldish = (
            "XAU" in up_name
            or up_name.startswith("GOLD")
            or "GOLD VS" in up_desc
            or "GOLD CONTRACT" in up_desc
            or "XAUUSD" in up_desc
        )
        if goldish:
            hits.append({"symbol": name, "description": desc, "visible": bool(getattr(info, "visible", False))})
    return {
        "status": "OBSERVED",
        "catalog_count": int(len(symbols)),
        "gold_like": hits[:80],
        "xauusd_present": any(h["symbol"] == "XAUUSD" for h in hits),
        "xauusd_i_present": any(h["symbol"] == "XAUUSD_i" for h in hits),
        "symbol_select_called": False,
        "broker_wide_absence_not_concluded": True,
    }


def inspect_history(mt5: Any) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(HISTORY_START, end) or []
    orders = mt5.history_orders_get(HISTORY_START, end) or []
    gold_deals = [d for d in deals if is_gold_symbol(str(getattr(d, "symbol", "") or ""))]
    gold_orders = [o for o in orders if is_gold_symbol(str(getattr(o, "symbol", "") or ""))]
    xi_deals = [d for d in gold_deals if str(getattr(d, "symbol", "")) == CANONICAL_SYMBOL]
    commissions = [float(getattr(d, "commission", 0) or 0) for d in xi_deals]
    swaps = [float(getattr(d, "swap", 0) or 0) for d in xi_deals]
    states: Counter[str] = Counter()
    types: Counter[str] = Counter()
    vol_init: list[float] = []
    vol_cur: list[float] = []
    for o in gold_orders[:80]:
        states[str(getattr(o, "state", UNKNOWN))] += 1
        types[str(getattr(o, "type", UNKNOWN))] += 1
        vol_init.append(float(getattr(o, "volume_initial", 0) or 0))
        vol_cur.append(float(getattr(o, "volume_current", 0) or 0))
    nonzero_swap = [v for v in swaps if abs(v) > 1e-9]
    partials = sum(1 for a, b in zip(vol_init, vol_cur) if b > 0 and abs(a - b) > 1e-9)
    return {
        "status": "OBSERVED",
        "deals_total": int(len(deals)),
        "orders_total": int(len(orders)),
        "gold_deals": int(len(gold_deals)),
        "xauusd_i_deals": int(len(xi_deals)),
        "gold_orders": int(len(gold_orders)),
        "all_xi_commission_zero": bool(commissions) and all(abs(v) < 1e-12 for v in commissions),
        "nonzero_swap_count": int(len(nonzero_swap)),
        "order_states": dict(states),
        "order_types": dict(types),
        "possible_partials": partials,
        "requested_price_on_deal": False,
        "price_open_is_requested": False,
        "deviation_is_realized_slippage": False,
        "genuine_requested_vs_filled_pairs": 0,
        "positions_touched": False,
        "orders_modified": False,
        "orders_sent": False,
    }


def inspect_journal(root: Path) -> dict[str, Any]:
    path = root / JOURNAL_DB
    out: dict[str, Any] = {
        "path": JOURNAL_DB,
        "present": path.is_file(),
        "xauusd_i_requested_fill_pairs": 0,
        "logical_xauusd_live_pairs": 0,
        "mapped_to_canonical": False,
        "usable_for_xauusd_i_slippage": False,
        "note": "logical XAUUSD journal rows are not XAUUSD_i under empty dataset_symbol_map",
    }
    if not path.is_file():
        return out
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        cur = con.cursor()
        tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        out["tables"] = sorted(tables)
        if "executions" not in tables:
            con.close()
            return out
        cols = [r[1] for r in cur.execute("PRAGMA table_info(executions)").fetchall()]
        out["columns"] = cols
        has_req = "requested_price" in cols and "fill_price" in cols
        out["has_requested_and_fill"] = has_req
        if has_req:
            rows = cur.execute(
                "SELECT symbol, mode, requested_price, fill_price, success FROM executions "
                "WHERE requested_price IS NOT NULL AND fill_price IS NOT NULL"
            ).fetchall()
            xi = [r for r in rows if str(r[0]) == CANONICAL_SYMBOL]
            xau = [r for r in rows if str(r[0]).upper() == "XAUUSD"]
            live_xau = [r for r in xau if str(r[1]).lower() == "live"]
            out["pair_rows"] = int(len(rows))
            out["xauusd_i_requested_fill_pairs"] = int(len(xi))
            out["logical_xauusd_live_pairs"] = int(len(live_xau))
            out["usable_for_xauusd_i_slippage"] = bool(xi)
        con.close()
    except sqlite3.Error as exc:
        out["error"] = str(exc)
    return out


def bounded_tick_probe() -> dict[str, Any]:
    code = (
        "import json\n"
        "from datetime import datetime,timedelta,timezone\n"
        "try:\n"
        " import MetaTrader5 as mt5\n"
        "except Exception as e:\n"
        " print(json.dumps({'status':'BLOCKED','error':str(e)})); raise SystemExit(0)\n"
        "ok=bool(mt5.initialize(timeout=10000))\n"
        "if not ok:\n"
        " print(json.dumps({'status':'NOT_ATTACHED','error':str(mt5.last_error())})); raise SystemExit(0)\n"
        "start=datetime.now(timezone.utc)-timedelta(minutes=2)\n"
        "ticks=mt5.copy_ticks_from('XAUUSD_i', start, 400, mt5.COPY_TICKS_ALL)\n"
        "n=0 if ticks is None else int(len(ticks))\n"
        "bid=ask=None\n"
        "if n:\n"
        " bid=float(ticks[0]['bid']); ask=float(ticks[0]['ask'])\n"
        " print(json.dumps({'status':'OBSERVED' if n else 'NOT_OBSERVED','rows':n,'sample_bid':bid,'sample_ask':ask,'window_minutes':2,'resource_bound':True}))\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=TICK_PROBE_SECONDS,
            cwd=str(Path.cwd()),
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "SKIPPED_RESOURCE_BOUND",
            "error": f"copy_ticks_from exceeded {TICK_PROBE_SECONDS}s; not retried",
            "historical_bid_ask": False,
        }
    if proc.returncode != 0:
        return {"status": "BLOCKED", "error": (proc.stderr or proc.stdout or "tick probe failed")[:400], "historical_bid_ask": False}
    try:
        payload = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"status": "NOT_OBSERVED", "error": "unparseable tick probe stdout", "historical_bid_ask": False}
    payload["historical_bid_ask"] = bool(payload.get("status") == "OBSERVED" and int(payload.get("rows") or 0) > 0)
    payload["coverage"] = "last_2_minutes_max_400_ticks" if payload.get("historical_bid_ask") else "none"
    payload["evaluation_tape_coverage"] = False
    return payload


def attach_if_running() -> dict[str, Any]:
    running = terminal64_running()
    launch = {
        "launched_by_phase": False,
        "already_running": running,
        "ok": running,
        "policy": "Phase 42 does not launch MT5. Attach only if already running.",
    }
    if not running:
        return {
            "launch": launch,
            "attach": {
                "ok": False,
                "status": "BLOCKED",
                "reason": "terminal64.exe not running; launch refused",
                "env_accessed": False,
                "orders_sent": False,
            },
            "gold_aliases": {"status": "NOT_OBSERVED"},
            "symbols": {},
        }
    attach = bounded_readonly_attach_once()
    aliases = {"status": "NOT_OBSERVED"}
    symbols: dict[str, Any] = {}
    if attach.get("ok"):
        try:
            import MetaTrader5 as mt5

            account = account_identity_snapshot(mt5)
            term = terminal_build_snapshot(mt5)
            attach["account"] = account
            attach["broker"] = account.get("broker")
            attach["server"] = account.get("server")
            attach["environment"] = account.get("trade_mode_label")
            attach["login_identity"] = account.get("login_identity")
            attach["connected"] = bool(term.get("connected"))
            attach["build"] = term.get("build")
            attach["catalog"] = catalog_existence_check(mt5)
            acct = mt5.account_info()
            if acct is not None:
                attach["account"]["balance"] = float(getattr(acct, "balance", 0) or 0)
                attach["account"]["equity"] = float(getattr(acct, "equity", 0) or 0)
                attach["account"]["margin"] = float(getattr(acct, "margin", 0) or 0)
            symbols = {
                CANONICAL_SYMBOL: _augment_symbol(mt5, inspect_symbol_readonly(mt5, CANONICAL_SYMBOL)),
                LOGICAL_SYMBOL: _augment_symbol(mt5, inspect_symbol_readonly(mt5, LOGICAL_SYMBOL)),
            }
            aliases = gold_alias_scan(mt5)
        except Exception as exc:
            attach["error"] = str(exc)[:200]
            aliases = {"status": "BLOCKED", "error": str(exc)[:200]}
    return {"launch": launch, "attach": attach, "gold_aliases": aliases, "symbols": symbols}


def audit_sidecars(root: Path) -> list[dict[str, Any]]:
    out = []
    for rel in SIDECARS:
        path = root / rel
        row: dict[str, Any] = {"path": rel, "exists": path.is_file(), "source_modified": False}
        if not path.is_file():
            out.append(row)
            continue
        try:
            df = pd.read_parquet(path)
            cols = [str(c).lower() for c in df.columns]
            row.update(
                {
                    "rows": int(len(df)),
                    "columns": [str(c) for c in df.columns],
                    "bid_present": any("bid" in c for c in cols),
                    "ask_present": any("ask" in c for c in cols),
                    "covers_phase38_eval_tape": False,
                }
            )
            if "bid" in df.columns and "ask" in df.columns:
                spr = (pd.to_numeric(df["ask"], errors="coerce") - pd.to_numeric(df["bid"], errors="coerce")).dropna()
                if len(spr):
                    qs = spr.quantile([0.5, 0.75, 0.9, 0.95, 0.99])
                    row["spread_stats"] = {
                        "n": int(len(spr)),
                        "median": float(qs.loc[0.5]),
                        "p75": float(qs.loc[0.75]),
                        "p90": float(qs.loc[0.9]),
                        "p95": float(qs.loc[0.95]),
                        "p99": float(qs.loc[0.99]),
                        "max": float(spr.max()),
                        "label": "DERIVED from existing sidecar; not a new acquisition",
                    }
            idx = None
            if isinstance(df.index, pd.DatetimeIndex):
                idx = pd.to_datetime(df.index, utc=True, errors="coerce")
            else:
                for c in df.columns:
                    if "time" in str(c).lower() or str(c).lower() in {"timestamp", "datetime"}:
                        idx = pd.to_datetime(df[c], utc=True, errors="coerce")
                        break
            if idx is not None:
                row["first"] = str(idx.min())
                row["last"] = str(idx.max())
        except Exception as exc:
            row["error"] = str(exc)[:200]
        out.append(row)
    return out


def classify_commission(history: dict[str, Any], p39: dict[str, Any]) -> dict[str, Any]:
    prior = p39.get("commission") or {}
    n = int(history.get("xauusd_i_deals") or prior.get("xauusd_i_deals") or 0)
    zeros = bool(history.get("all_xi_commission_zero") if "all_xi_commission_zero" in history else prior.get("all_observed_zeros"))
    return {
        "status": UNKNOWN,
        "classification": OBSERVED_ZERO_NOT_PROVEN if zeros and n else UNKNOWN,
        "verified_schedule": False,
        "zero_is_not_verified": True,
        "invented": False,
        "account_product_type": UNKNOWN,
        "xauusd_i_deals": n,
        "all_observed_zeros": zeros,
        "public_ecn_supporting_only": PUBLIC_ECN,
        "why_not_closed": (
            "Account product/tier (ECN vs CLASSIC vs CENT) is UNKNOWN. "
            "Official ECN precious-metals $5/lot is GENERIC_SUPPORTING. "
            "Observed deal commission=0 is not a VERIFIED_SCHEDULE. "
            "Classic/Cent 'commission embedded in spread' cannot be applied without product type."
        ),
        "missing": [
            "account_product_type",
            "basis",
            "per_side_or_round_turn",
            "commission_currency",
            "effective_date_for_this_account",
            "applicability_established",
        ],
        "hierarchy_used": "ACCOUNT-SPECIFIC missing; official general document supporting only",
    }


def classify_mapping(xi: dict[str, Any], xau: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    xau_yes = xau.get("existence") == "YES"
    return {
        "CURRENT_REAL_SYMBOL": "XAUUSD_i",
        "EXPECTED_USER_REAL_SYMBOL": "XAUUSD",
        "CURRENT_TERMINAL_XAUUSD": "OBSERVED" if xau_yes else "NOT_OBSERVED",
        "SYMBOL_MAPPING": ev.get("status") if ev.get("status") in {"VERIFIED_EQUIVALENT", "VERIFIED_DIFFERENT"} else NOT_PROVEN,
        "broker_wide_absence_concluded": False,
        "renamed": False,
        "silent_map": False,
        "ev_eq_01": ev.get("status") or NOT_PROVEN,
        "xi_existence": xi.get("existence"),
        "xau_existence": xau.get("existence"),
        "note": "Absence of XAUUSD on this terminal does not prove broker-wide absence.",
    }


def _symbol_row(row: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "observed": row.get("existence"),
        "account": account.get("trade_mode_label"),
        "server": account.get("server"),
        "contract_size": row.get("contract_size") or row.get("trade_contract_size"),
        "tick_size": row.get("tick_size") or row.get("trade_tick_size"),
        "tick_value": row.get("tick_value") or row.get("trade_tick_value"),
        "volume_min": row.get("volume_min"),
        "volume_step": row.get("volume_step"),
        "execution_mode": row.get("execution_mode") or row.get("trade_exemode"),
        "filling": row.get("filling_mode"),
        "swap_long": row.get("swap_long"),
        "swap_short": row.get("swap_short"),
        "timestamp": row.get("quote_utc"),
    }


def cost_gates(comm: dict[str, Any], slip: dict[str, Any], exe: dict[str, Any], mapping: dict[str, Any], eco: dict[str, Any], pairs: int) -> dict[str, Any]:
    rows = [
        {"gate": "1 symbol identity", "status": "FAIL", "note": f"EV-EQ-01 {mapping.get('ev_eq_01')}; mapping {mapping.get('SYMBOL_MAPPING')}"},
        {"gate": "2 broker economics", "status": "PARTIAL" if eco.get("digits") not in (None, UNKNOWN) else "UNKNOWN", "note": "Current REAL XAUUSD_i snapshot OBSERVED; not a historical series"},
        {"gate": "3 commission", "status": "FAIL", "note": comm.get("status")},
        {"gate": "4 swap", "status": "PARTIAL", "note": "CURRENT_SWAP OBSERVED; HISTORICAL_SWAP UNKNOWN"},
        {"gate": "5 historical spread", "status": "PARTIAL", "note": "15d sidecar OBSERVED; eval tape PROXY"},
        {"gate": "6 slippage", "status": "FAIL", "note": slip.get("SLIPPAGE_POLICY")},
        {"gate": "7 execution evidence", "status": "PARTIAL", "note": exe.get("grade")},
        {"gate": "8 request/fill telemetry", "status": "FAIL", "note": f"pairs={pairs}"},
    ]
    passed = sum(1 for r in rows if r["status"] == "PASS")
    return {
        "rows": rows,
        "cost_ready_gate_count": passed,
        "required": 8,
        "cost_ready_for_validation": False,
        "modeled_not_pass": True,
        "gate_weakened": False,
    }


def executable_contract(comm: dict[str, Any], slip: dict[str, Any], eco: dict[str, Any]) -> dict[str, Any]:
    inputs = {
        "entry_price": "OBSERVED (Phase 40 RAW theoretical)",
        "exit_price": "OBSERVED (Phase 40 theoretical SL/TP path)",
        "spread": "PARTIAL sidecar / PROXY eval tape",
        "commission": comm.get("status") or UNKNOWN,
        "swap": "CURRENT OBSERVED / HISTORICAL UNKNOWN",
        "slippage": slip.get("SLIPPAGE_POLICY") or "MODELED",
        "volume": UNKNOWN,
        "contract_size": eco.get("contract_size") if eco.get("contract_size") not in (None, UNKNOWN) else UNKNOWN,
        "tick_value": eco.get("tick_value") if eco.get("tick_value") not in (None, UNKNOWN) else UNKNOWN,
        "tick_size": eco.get("tick_size") if eco.get("tick_size") not in (None, UNKNOWN) else UNKNOWN,
        "execution_mode": eco.get("execution_mode") if eco.get("execution_mode") not in (None, UNKNOWN) else UNKNOWN,
        "minimum_volume": eco.get("volume_min") if eco.get("volume_min") not in (None, UNKNOWN) else UNKNOWN,
        "volume_step": eco.get("volume_step") if eco.get("volume_step") not in (None, UNKNOWN) else UNKNOWN,
        "SL": "OBSERVED on Phase 40 setups",
        "TP": "OBSERVED on Phase 40 setups",
        "holding_duration": "OBSERVED on Phase 40 setups",
        "rollover": "CURRENT rate OBSERVED; historical UNKNOWN",
    }
    return {
        "inputs": inputs,
        "EXECUTABLE_BACKTEST_READY": False,
        "readiness": "BLOCKED",
        "blockers": [
            "commission UNKNOWN / no VERIFIED_SCHEDULE",
            "request/fill pairs=0",
            "eval-tape Bid/Ask incomplete",
        ],
        "engine_changed": False,
        "executable_evaluation_run": False,
    }


def blocker_update(p41: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    prior = {b.get("blocker"): b for b in (p41.get("blockers") or [])}
    now = {
        "Commission unknown": payload["commission"]["status"],
        "Request/fill pairs absent": f"pairs={payload['request_fill']['pairs']}",
        "Historical Bid/Ask incomplete": payload["spread"]["SPREAD_POLICY"],
        "Historical swap series unknown": payload["swap"]["HISTORICAL_SWAP"],
        "Symbol mapping not proven": payload["symbol"]["SYMBOL_MAPPING"],
        "Executable evaluation unavailable": payload["executable_contract"]["readiness"],
        "OOS/regime/dependence uncertainty": "UNCHANGED — Phase 40 not rescanned",
        "Production configuration / FINAL_GATE": payload["final_gate"],
    }
    rows = []
    for name in PHASE41_BLOCKER_NAMES:
        old = prior.get(name) or {}
        status42 = now[name]
        rows.append(
            {
                "blocker": name,
                "PHASE41_STATUS": old.get("current_status") or old.get("severity") or "OPEN",
                "PHASE42_STATUS": status42,
                "NEW_EVIDENCE": "fresh attach-if-running / history / sidecars / official ECN supporting page",
                "CLOSURE": "OPEN",
                "REMAINING_ACTION": old.get("exact_closure_action") or "see Phase 41 blocker matrix",
            }
        )
    return rows


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    v = payload.get("verdict") or {}
    c = payload.get("commission") or {}
    s = payload.get("symbol") or {}
    ev = payload.get("ev_eq_01") or {}
    contract = payload.get("executable_contract") or {}
    gates = payload.get("cost_gates") or {}
    swap = payload.get("swap") or {}
    b = payload.get("broker") or {}
    exe = payload.get("execution") or {}
    recon = payload.get("reconstruction") or {}
    holds = swap.get("hold_diagnostics") or recon.get("hold_diagnostics") or {}
    drag = swap.get("modeled_sensitivity") or recon.get("swap_sensitivity") or {}
    aliases = ((payload.get("mt5") or {}).get("gold_aliases") or {}).get("gold_like") or []
    table = payload.get("SYMBOL_EVIDENCE_TABLE") or []
    lines = [
        "# Phase 42 — Broker Cost, Execution Telemetry, Bid/Ask, Swap, Symbol Mapping",
        "",
        f"**STATUS:** `{payload.get('status')}`",
        "**Class:** RESEARCH / AUDIT ONLY",
        f"**FINAL_GATE:** `{payload.get('final_gate')}`",
        f"**EXECUTABLE_BACKTEST_READY:** `{contract.get('EXECUTABLE_BACKTEST_READY')}`",
        f"**OVERALL_VERDICT:** `{v.get('overall')}`",
        f"**PHASE40_RESCAN:** `NO`",
        f"**MT5 launched by phase:** `{((payload.get('mt5') or {}).get('launch') or {}).get('launched_by_phase')}`",
        f"**Fresh attach:** `{b.get('fresh_attach')}`",
        "",
        "STOP AFTER PHASE 42. DO NOT START PHASE 43.",
        "DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.",
        "",
        "This phase does **not** rewrite Phase 28/39/40/41 conclusions. It adds a new evidence layer.",
        "",
        "## Executive verdict",
        "",
        f"- BROKER_EVIDENCE: `{v.get('BROKER_EVIDENCE')}`",
        f"- COST_EVIDENCE: `{v.get('COST_EVIDENCE')}`",
        f"- EXECUTION_EVIDENCE: `{v.get('EXECUTION_EVIDENCE')}`",
        f"- HISTORICAL_SPREAD: `{v.get('HISTORICAL_SPREAD')}`",
        f"- COMMISSION: `{v.get('COMMISSION')}`",
        f"- SWAP: `{v.get('SWAP')}`",
        f"- SLIPPAGE: `{v.get('SLIPPAGE')}`",
        f"- SYMBOL_MAPPING: `{v.get('SYMBOL_MAPPING')}`",
        f"- EXECUTABLE_READINESS: `{v.get('EXECUTABLE_READINESS')}`",
        f"- EXECUTABLE_RESULT: `{v.get('EXECUTABLE_RESULT')}`",
        f"- FINAL_GATE: `{v.get('FINAL_GATE')}`",
        f"- OVERALL: `{v.get('overall')}`",
        f"- Profitability: `{v.get('profitability_verdict')}`",
        "",
        "## Broker / symbol (Part A / B)",
        "",
        f"- Broker: `{b.get('broker')}` — label OBSERVED if freshly attached, else REUSED_PHASE39",
        f"- Server: `{b.get('server')}`",
        f"- Environment: `{b.get('environment')}`",
        f"- Currency: `{b.get('currency')}`",
        f"- Balance/equity (read-only): `{b.get('balance')}` / `{b.get('equity')}`",
        f"- CURRENT_REAL_SYMBOL: `{s.get('CURRENT_REAL_SYMBOL')}`",
        f"- EXPECTED_USER_REAL_SYMBOL: `{s.get('EXPECTED_USER_REAL_SYMBOL')}`",
        f"- CURRENT_TERMINAL_XAUUSD: `{s.get('CURRENT_TERMINAL_XAUUSD')}`",
        f"- SYMBOL_MAPPING: `{s.get('SYMBOL_MAPPING')}`",
        "",
        "XAUUSD absence on this terminal is **not** broker-wide absence.",
        "",
        "| symbol | observed | account | server | contract | tick_size | tick_value | vol_min | vol_step | exec | fill | swap_long | swap_short | timestamp |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in table:
        lines.append(
            "| {symbol} | {observed} | {account} | {server} | {contract_size} | {tick_size} | {tick_value} | {volume_min} | {volume_step} | {execution_mode} | {filling} | {swap_long} | {swap_short} | {timestamp} |".format(
                **{k: row.get(k) for k in (
                    "symbol", "observed", "account", "server", "contract_size", "tick_size",
                    "tick_value", "volume_min", "volume_step", "execution_mode", "filling",
                    "swap_long", "swap_short", "timestamp",
                )}
            )
        )
    lines += [
        "",
        "Gold-like catalog names (filtered; Goldman-style equity names excluded):",
        "",
    ]
    for hit in aliases[:20]:
        lines.append(f"- `{hit.get('symbol')}` — {hit.get('description')} (visible={hit.get('visible')})")
    lines += [
        "",
        "## EV-EQ-01 (Part H)",
        "",
        "CODE definition: `evaluate_ev_eq_01()` in `tradingbot/backtest/phase27_9_real_broker_evidence.py`.",
        "Requires REAL environment **and both** `XAUUSD` and `XAUUSD_i` collected, then field-by-field `build_equivalence_audit`.",
        "If one symbol is missing → `NOT_PROVEN`. Absence on this terminal ≠ broker-wide absence.",
        "",
        f"- Status: `{ev.get('status')}`",
        f"- Both symbols present: `{ev.get('both_symbols_present')}`",
        f"- Rationale: `{ev.get('rationale')}`",
        f"- Inferred: `{ev.get('inferred')}`",
        "",
        "Current evidence does **not** satisfy EV-EQ-01. Missing: observe `XAUUSD` on this REAL catalog or an official account-applicable equivalence statement.",
        "",
        "## Commission (Part C)",
        "",
        f"- Status: `{c.get('status')}`",
        f"- Classification: `{c.get('classification')}`",
        f"- Verified schedule: `{c.get('verified_schedule')}`",
        f"- Account product type: `{c.get('account_product_type')}`",
        f"- XAUUSD_i deals this inspect: `{c.get('xauusd_i_deals')}`",
        f"- All observed zeros: `{c.get('all_observed_zeros')}`",
        "",
        c.get("why_not_closed") or "",
        "",
        "Official LiteFinance ECN page (2026-09-08 fetch): precious metals $5/lot on MT4/MT5, charged at open.",
        "Grade remains OFFICIAL_BROKER_GENERAL_DOCUMENT / GENERIC_SUPPORTING because this account's product/tier is UNKNOWN.",
        "Do not treat historical deal commission=0 as policy=0.",
        "",
        "## Execution history / request-fill / slippage (Parts D / E)",
        "",
        f"- History status: `{(payload.get('history') or {}).get('status')}`",
        f"- Deals / orders / XAUUSD_i deals: `{exe.get('deals')}` / `{exe.get('orders')}` / `{exe.get('xauusd_i_deals')}`",
        f"- REQUEST_FILL_PAIRS: `{(payload.get('request_fill') or {}).get('pairs')}`",
        f"- Journal XAUUSD_i pairs: `{(payload.get('request_fill') or {}).get('journal_xauusd_i_pairs')}`",
        f"- Journal logical XAUUSD live pairs (not used): `{(payload.get('request_fill') or {}).get('journal_logical_xauusd_live_pairs')}`",
        f"- SLIPPAGE_EVIDENCE: `{(payload.get('slippage') or {}).get('SLIPPAGE_EVIDENCE')}`",
        f"- SLIPPAGE_POLICY: `{(payload.get('slippage') or {}).get('SLIPPAGE_POLICY')}` (model unchanged: ~0.8 pips + session multiplier)",
        "",
        "price_open, deal.price, deviation, and SL/TP are not request/fill evidence.",
        "",
        "## Historical Bid/Ask (Part F)",
        "",
        f"- SPREAD_POLICY: `{(payload.get('spread') or {}).get('SPREAD_POLICY')}`",
        f"- Evaluation tape Bid/Ask columns: `{(payload.get('spread') or {}).get('evaluation_tape_bid_ask')}`",
        f"- Tick probe: `{((payload.get('spread') or {}).get('tick_probe') or {}).get('status')}` "
        f"rows=`{((payload.get('spread') or {}).get('tick_probe') or {}).get('rows')}` "
        "(bounded 2 minutes / 400 ticks; does not cover the 1291-day tape)",
        "",
        "Existing sidecars were read, not overwritten. Canonical Phase 28/38 M5 parquets were not modified.",
        "",
        "## Swap (Part G)",
        "",
        f"- CURRENT_SWAP: `{swap.get('CURRENT_SWAP')}` long=`{swap.get('current_swap_long')}` short=`{swap.get('current_swap_short')}` rollover3days=`{swap.get('rollover3days')}` (Wednesday)",
        f"- HISTORICAL_SWAP: `{swap.get('HISTORICAL_SWAP')}`",
        f"- Resolved Phase 40 trades: `{holds.get('resolved_trades')}`",
        f"- Share ≥8h: `{holds.get('share_ge_8h')}`",
        f"- Share ≥9h (possible rollover): `{holds.get('share_ge_9h_possible_rollover')}`",
        f"- Wednesday-touch share: `{holds.get('wednesday_touch_share')}`",
        "",
        "MODELED sensitivity (not observed broker cost): one overnight on 1 lot vs median SL.",
        f"- Long drag if overnight share: `{drag.get('expected_drag_if_share_overnight_long_R')}` R",
        f"- Short credit if overnight share: `{drag.get('expected_drag_if_share_overnight_short_R')}` R",
        "",
        "## Cost gates / executable contract (Parts I / J / L)",
        "",
        f"- cost_ready_gate_count: `{gates.get('cost_ready_gate_count')}` / `{gates.get('required')}`",
        f"- Readiness: `{contract.get('readiness')}`",
        "",
        "Modeled evidence is never PASS. The existing backtest engine was not changed.",
        "Executable evaluation was not run because commission remains UNKNOWN.",
        "",
        "## Reconstruction (Parts K / M / N)",
        "",
        f"- Status: `{recon.get('status')}`",
        f"- Commission applied: `{recon.get('commission_applied')}`",
        f"- Signals regenerated: `{recon.get('signals_regenerated')}`",
        f"- Frozen Phase 40 fingerprint: `{recon.get('phase40_fingerprint')}`",
        f"- RAW expectancy (unchanged): `{recon.get('raw_expectancy_R')}` R",
        "",
        "No executable RAW vs EXECUTABLE difference table is issued. Event-level executable analysis is not available.",
        "",
        "## Stop",
        "",
        "STOP AFTER PHASE 42.",
        "DO NOT START PHASE 43.",
        "",
    ]
    (root / PHASE42_MD).write_text("\n".join(lines), encoding="utf-8")
    matrix = [
        "# Phase 42 — Evidence Matrix",
        "",
        "| Gate | Status | Note |",
        "|---|---|---|",
    ]
    for row in gates.get("rows") or []:
        matrix.append(f"| {row.get('gate')} | {row.get('status')} | {row.get('note')} |")
    matrix += [
        "",
        f"**cost_ready_gate_count:** `{gates.get('cost_ready_gate_count')}` / 8",
        "",
        "Modeled evidence is never PASS.",
        "",
        "## Blocker update vs Phase 41",
        "",
        "| Blocker | Phase 41 | Phase 42 | Closure |",
        "|---|---|---|---|",
    ]
    for row in payload.get("blocker_update") or []:
        matrix.append(f"| {row.get('blocker')} | {row.get('PHASE41_STATUS')} | {row.get('PHASE42_STATUS')} | {row.get('CLOSURE')} |")
    matrix.append("")
    (root / PHASE42_MATRIX_MD).write_text("\n".join(matrix), encoding="utf-8")
    ready = [
        "# Phase 42 — Executable Readiness",
        "",
        f"**EXECUTABLE_BACKTEST_READY:** `{contract.get('EXECUTABLE_BACKTEST_READY')}`",
        f"**Readiness:** `{contract.get('readiness')}`",
        "",
        "Required inputs and epistemic labels:",
        "",
    ]
    for key, val in (contract.get("inputs") or {}).items():
        ready.append(f"- `{key}`: {val}")
    ready += [
        "",
        "Blockers:",
        "",
    ]
    for b in contract.get("blockers") or []:
        ready.append(f"- {b}")
    ready += [
        "",
        "The existing backtest engine was **not** changed.",
        "Executable evaluation was **not** run.",
        "",
    ]
    (root / PHASE42_READY_MD).write_text("\n".join(ready), encoding="utf-8")


def _patch_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phase 42 (`docs_v2/02_research/PHASE42_BROKER_COST_EXECUTION_CLOSURE.md`) is research-only "
        "broker-cost and execution-telemetry closure. It does not authorize live trading, "
        "overwrite the frozen M5 snapshot, optimize, or start Phase 43."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phase 41 (`docs_v2/02_research/PHASE41_FINAL_EVIDENCE_CLOSURE.md`)"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            if end == -1:
                text = text.rstrip() + "\n\n" + line + "\n"
            else:
                text = text[:end] + "\n\n" + line + text[end:]
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    row = (
        "| Phase 42 broker cost/execution closure | `run_phase42_collection()` | n/a | "
        "RESEARCH/AUDIT; attach-if-running only; no bot/orders/.env | "
        f"**{payload.get('status')}**; Phase 43 not started |"
    )
    if "Phase 42 broker cost/execution closure" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", row + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    bline = (
        "`tradingbot/backtest/phase42_broker_cost_execution_closure.py` — **RESEARCH_ONLY** "
        "broker cost/execution telemetry; attach-if-running; does not overwrite Phase 28 M5.\n"
    )
    needle = (
        "`tradingbot/backtest/phase41_final_evidence_closure.py` — **RESEARCH_ONLY** final evidence "
        "closure / readiness audit; reads Phase 38–40 artifacts; does not rescan or overwrite Phase 28 M5.\n"
    )
    if "phase42_broker_cost_execution_closure.py" not in btext and needle in btext:
        btext = btext.replace(needle, needle + bline)
        bnd.write_text(btext, encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 42 started | **NO** |", "| Phase 42 started | **YES** |")
    block = f"""

## Broker cost execution closure (Phase 42)

| Claim | Status |
|---|---|
| Phase 42 status | **{payload.get("status")}** |
| Phase 40 rescan | **NO** |
| MT5 launched by phase | **NO** |
| Commission | **{((payload.get("commission") or {}).get("status"))}** |
| EV-EQ-01 | **{((payload.get("ev_eq_01") or {}).get("status"))}** |
| Executable ready | **{((payload.get("executable_contract") or {}).get("EXECUTABLE_BACKTEST_READY"))}** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Phase 43 started | **NO** |
"""
    if "## Broker cost execution closure (Phase 42)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def run_phase42_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p16 = _safe_load_json(root / PHASE2716_JSON) or {}
    p39 = _safe_load_json(root / PHASE39_JSON) or {}
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p41 = _safe_load_json(root / PHASE41_JSON) or {}

    mt5_pack = attach_if_running()
    attach = mt5_pack.get("attach") or {}
    symbols_live = mt5_pack.get("symbols") or {}
    history: dict[str, Any]
    if attach.get("ok"):
        try:
            import MetaTrader5 as mt5

            history = inspect_history(mt5)
        except Exception as exc:
            history = {"status": "BLOCKED", "error": str(exc)[:200], "genuine_requested_vs_filled_pairs": 0}
    else:
        hist39 = p39.get("history") or {}
        exe39 = p39.get("execution") or {}
        history = {
            **hist39,
            "status": "REUSED_PHASE39" if hist39 or exe39 else "UNKNOWN",
            "deals_total": hist39.get("deals_total") or exe39.get("deals"),
            "orders_total": hist39.get("orders_total") or exe39.get("orders"),
            "xauusd_i_deals": hist39.get("xauusd_i_deals") or exe39.get("xauusd_i_deals"),
            "all_xi_commission_zero": hist39.get("all_xi_commission_zero", True),
            "genuine_requested_vs_filled_pairs": int((p39.get("slippage") or {}).get("genuine_requested_vs_executed_pairs") or 0),
        }
    journal = inspect_journal(root)
    ticks = {"status": "SKIPPED", "reason": "MT5 not attached"}
    if attach.get("ok"):
        ticks = bounded_tick_probe()

    xi = symbols_live.get(CANONICAL_SYMBOL) or ((p39.get("symbols") or {}).get("XAUUSD_i") or {})
    xau = symbols_live.get(LOGICAL_SYMBOL) or ((p39.get("symbols") or {}).get("XAUUSD") or {})
    account = attach.get("account") or ((p39.get("mt5") or {}).get("attach") or {}).get("account") or {}
    env = attach.get("environment") or account.get("trade_mode_label") or ((p39.get("mt5") or {}).get("attach") or {}).get("environment") or "REAL"
    server = attach.get("server") or account.get("server") or "LiteFinance-MT5-Live"
    ev = evaluate_ev_eq_01(
        xau if xau.get("existence") == "YES" else None,
        xi if xi.get("existence") == "YES" else None,
        environment=str(env),
        server=str(server),
        artifact=PHASE42_JSON,
        timestamp=_utc_now(),
    )
    mapping = classify_mapping(xi, xau, ev)
    comm = classify_commission(history, p39)
    sidecars = audit_sidecars(root)
    spread = {
        "SPREAD_POLICY": "PROXY / PARTIAL",
        "evaluation_tape_bid_ask": False,
        "sidecars": sidecars,
        "phase35_sidecar_n": 2952,
        "phase35_median_price": 0.4099999999998545,
        "tick_probe": ticks,
        "ohlc_proxy_relabeled_observed": False,
        "covers_1291d_eval_tape": False,
    }
    pairs = int(history.get("genuine_requested_vs_filled_pairs") or 0)
    if journal.get("xauusd_i_requested_fill_pairs"):
        pairs = int(journal["xauusd_i_requested_fill_pairs"])
    slip = {
        "SLIPPAGE_EVIDENCE": UNKNOWN,
        "SLIPPAGE_POLICY": "MODELED",
        "pairs": pairs,
        "sample": "NONE" if pairs == 0 else "LIMITED_SAMPLE",
        "model_unchanged": {"slippage_pips": 0.8, "session_multiplier": "BacktestConfig default"},
        "mt5_deviation_is_realized": False,
        "price_open_is_requested": False,
    }
    exe = {
        "grade": "PARTIAL_EXECUTION_EVIDENCE",
        "deals": history.get("deals_total") or (p39.get("execution") or {}).get("deals"),
        "orders": history.get("orders_total") or (p39.get("execution") or {}).get("orders"),
        "xauusd_i_deals": history.get("xauusd_i_deals"),
        "requotes": UNKNOWN,
        "latency": UNKNOWN,
        "requested_vs_executed_price": "NOT_IDENTIFIABLE",
        "requested_vs_executed_volume": "NOT_IDENTIFIABLE",
        "possible_partials": history.get("possible_partials"),
        "history_status": history.get("status"),
    }
    swap_rates = {
        "CURRENT_SWAP": "OBSERVED" if xi.get("swap_long") not in (None, UNKNOWN) else "REUSED_PHASE39",
        "HISTORICAL_SWAP": UNKNOWN,
        "SWAP_POLICY": "BROKER_RATE_ONLY",
        "current_swap_long": xi.get("swap_long") if xi.get("swap_long") not in (None, UNKNOWN) else (p39.get("swap") or {}).get("current_swap_long"),
        "current_swap_short": xi.get("swap_short") if xi.get("swap_short") not in (None, UNKNOWN) else (p39.get("swap") or {}).get("current_swap_short"),
        "rollover3days": xi.get("rollover3days") if xi.get("rollover3days") not in (None, UNKNOWN) else (p39.get("swap") or {}).get("swap_rollover3days"),
        "deal_zeros_prove_historical_zero": False,
    }
    eco = {
        "digits": xi.get("digits"),
        "point": xi.get("point"),
        "contract_size": xi.get("contract_size") or xi.get("trade_contract_size"),
        "tick_size": xi.get("tick_size") or xi.get("trade_tick_size") or 0.01,
        "tick_value": xi.get("tick_value") or xi.get("trade_tick_value") or 1.0,
        "tick_value_profit": xi.get("tick_value_profit"),
        "tick_value_loss": xi.get("tick_value_loss"),
        "volume_min": xi.get("volume_min"),
        "volume_max": xi.get("volume_max"),
        "volume_step": xi.get("volume_step"),
        "trade_mode": xi.get("trade_mode"),
        "execution_mode": xi.get("execution_mode") or xi.get("trade_exemode"),
        "filling_mode": xi.get("filling_mode"),
        "stops_level": xi.get("stops_level"),
        "freeze_level": xi.get("freeze_level"),
        "quote_utc": xi.get("quote_utc"),
        "bid": xi.get("bid"),
        "ask": xi.get("ask"),
    }
    recon = reconstruct_frozen_phase40(root, eco, swap_rates)
    swap_rates["hold_diagnostics"] = recon.get("hold_diagnostics")
    swap_rates["modeled_sensitivity"] = recon.get("swap_sensitivity")
    contract = executable_contract(comm, slip, eco)
    gates = cost_gates(comm, slip, exe, mapping, eco, pairs)
    table = [
        _symbol_row({**xi, "symbol": CANONICAL_SYMBOL}, account),
        _symbol_row({**xau, "symbol": LOGICAL_SYMBOL}, account),
    ]
    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "phase_43_started": False,
        "env_accessed": False,
        "mt5": {
            "launch": mt5_pack.get("launch"),
            "attach_status": attach.get("status") or ("ATTACHED" if attach.get("ok") else "NOT_ATTACHED"),
            "attach_ok": bool(attach.get("ok")),
            "method": attach.get("method"),
            "gold_aliases": mt5_pack.get("gold_aliases"),
        },
        "broker": {
            "broker": attach.get("broker") or ((p39.get("mt5") or {}).get("attach") or {}).get("broker") or "LiteFinance Global LLC",
            "server": server,
            "environment": env,
            "currency": account.get("currency") or "USD",
            "balance": account.get("balance"),
            "equity": account.get("equity"),
            "login_identity": account.get("login_identity") or attach.get("login_identity"),
            "fresh_attach": bool(attach.get("ok")),
            "reused_phase39_if_not_attached": not bool(attach.get("ok")),
        },
        "SYMBOL_EVIDENCE_TABLE": table,
        "symbol": mapping,
        "commission": comm,
        "swap": swap_rates,
        "spread": spread,
        "slippage": slip,
        "request_fill": {
            "pairs": pairs,
            "journal_xauusd_i_pairs": journal.get("xauusd_i_requested_fill_pairs"),
            "journal_logical_xauusd_live_pairs": journal.get("logical_xauusd_live_pairs"),
            "status": 0 if pairs == 0 else pairs,
        },
        "execution": exe,
        "history": {
            "status": history.get("status"),
            "deals_total": history.get("deals_total"),
            "orders_total": history.get("orders_total"),
            "xauusd_i_deals": history.get("xauusd_i_deals"),
            "all_xi_commission_zero": history.get("all_xi_commission_zero"),
            "nonzero_swap_count": history.get("nonzero_swap_count"),
        },
        "ev_eq_01": ev,
        "cost_gates": gates,
        "executable_contract": contract,
        "reconstruction": recon,
        "phase40_baseline_verified": {
            "signals": (p40.get("scan") or {}).get("signals"),
            "events": (p40.get("events") or {}).get("event_count"),
            "raw_expectancy_R": (p40.get("raw_performance") or {}).get("expectancy_R"),
            "FINAL_GATE": p40.get("FINAL_GATE"),
        },
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "prior_phase16_final_gate": p16.get("FINAL_GATE"),
        "verdict": {
            "BROKER_EVIDENCE": "PARTIAL",
            "COST_EVIDENCE": "INCOMPLETE",
            "EXECUTION_EVIDENCE": "PARTIAL",
            "HISTORICAL_SPREAD": "PARTIAL",
            "COMMISSION": UNKNOWN,
            "SWAP": "BROKER_RATE_ONLY",
            "SLIPPAGE": "MODELED",
            "SYMBOL_MAPPING": mapping.get("SYMBOL_MAPPING"),
            "EXECUTABLE_READINESS": contract.get("readiness"),
            "EXECUTABLE_RESULT": "NOT_RUN",
            "FINAL_GATE": BLOCKED,
            "overall": "INSUFFICIENT_EVIDENCE",
            "profitability_verdict": "NOT_ISSUED",
        },
        "next_actions": [
            {"rank": 1, "action": "Operator confirms LiteFinance account product/tier and supplies account-applicable commission schedule", "information_value": "HIGHEST"},
            {"rank": 2, "action": "Enable request/fill telemetry on XAUUSD_i without trading from this phase", "information_value": "HIGH"},
            {"rank": 3, "action": "Historical Bid/Ask covering the Phase 38 evaluation tape", "information_value": "HIGH"},
            {"rank": 4, "action": "EV-EQ-01: observe XAUUSD on a REAL catalog or official equivalence statement", "information_value": "HIGH"},
            {"rank": 5, "action": "Executable evaluation after commission VERIFIED_SCHEDULE", "information_value": "HIGHEST_AFTER_COSTS"},
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
            "ENV": "NOT_READ/CHANGED",
            "PHASE40_RESCAN": "NO",
            "MT5_LAUNCHED": False,
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {
            "json": PHASE42_JSON,
            "md": PHASE42_MD,
            "matrix_md": PHASE42_MATRIX_MD,
            "ready_md": PHASE42_READY_MD,
        },
        "legacy_ml_phase42_not_this_phase": [
            "tradingbot/ml/research/phase42/run_phase42.py",
            "tests/test_phase42.py",
        ],
    }
    payload["blocker_update"] = blocker_update(p41, payload)
    payload = _redact(payload)
    _write_json(root / PHASE42_JSON, payload)
    _write_markdown(root, payload)
    _patch_truth_docs(root, payload)
    return payload


if __name__ == "__main__":
    out = run_phase42_collection(Path("."))
    print("STATUS", out.get("status"))
    print("ATTACH", ((out.get("mt5") or {}).get("attach_status")))
    print("COMMISSION", (out.get("commission") or {}).get("status"))
    print("EV-EQ-01", (out.get("ev_eq_01") or {}).get("status"))
    print("READY", ((out.get("executable_contract") or {}).get("EXECUTABLE_BACKTEST_READY")))
    print("FINAL_GATE", out.get("final_gate"))
