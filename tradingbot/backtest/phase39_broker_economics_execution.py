"""Phase 39 — broker economics + execution evidence resolution.

RESEARCH ONLY. Reuses the Phase 38 XAUUSD_i research tape. Does not send
orders, read .env, overwrite the frozen Phase 28 snapshot, optimize, or
start Phase 40.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness
from tradingbot.backtest.dataset_contract import classify_dataset_binding
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_9_real_broker_evidence import UNKNOWN
from tradingbot.backtest.phase27_15_cost_completeness_gate import (
    GATE_COMPONENTS,
    component_is_complete,
    cost_ready_for_validation,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_24_execution_cost_forensics import (
    DEAL_ENTRY_LABEL,
    DEAL_TYPE_LABEL,
    ORDER_STATE_LABEL,
    ORDER_TYPE_LABEL,
    is_gold_symbol,
)
from tradingbot.backtest.phase27_28_commission_evidence import OBSERVED_ZERO_NOT_PROVEN, POLICY as COMMISSION_POLICY
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
)
from tradingbot.backtest.phase28_1_full_baseline import _parse_ts, expand_raw_metrics
from tradingbot.backtest.phase28_2_walk_forward import TRAIN_FRAC, VAL_FRAC, OOS_FRAC, chronological_index_splits
from tradingbot.backtest.phase28_3_monte_carlo import N_PATHS, path_metrics, run_bootstrap, summarize_paths
from tradingbot.backtest.phase29_research_tape import content_fingerprint
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import event_representatives
from tradingbot.backtest.phase31_event_independence import assign_mechanical_events, event_metrics
from tradingbot.backtest.phase35_execution_reality import PHASE35_JSON
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import (
    CANONICAL_SYMBOL,
    EXTRA_SYMBOL_ATTRS,
    LOGICAL_SYMBOL,
    PHASE38_JSON,
    PHASE38_M5,
    PHASE38_M15,
    PHASE38_SETUPS,
    PREFERRED_EXE,
    _augment_symbol_fields,
    attach_with_path,
    discover_mt5_installations,
    launch_terminal,
    select_relevant_terminal,
    terminal64_running,
)
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import _attach_official_asian_range
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.gold_strategies.m5_london_sweep import asian_range, m5_asian_end_hour
from tradingbot.domain.position_logic import pip_size
from tradingbot.backtest.phase28_0_performance_foundation import load_parquet_utc

PHASE = "39"
PHASE39_JSON = "logs/phase39_broker_economics_execution.json"
PHASE39_MD = "docs_v2/02_research/PHASE39_BROKER_ECONOMICS_EXECUTION.md"
JOURNAL_DB = "data/trade_journal.db"
BIDASK_SIDECAR = "logs/phase27_26_xauusd_i_m5_bidask.parquet"
HISTORY_START = datetime(2018, 1, 1, tzinfo=timezone.utc)
MAX_HISTORY_DETAIL = 80
TICK_PROBE_SECONDS = 12
TICK_PROBE_COUNT = 400
RNG_SEED = 390039
MIN_EVENTS = 30
EVAL_DAYS = 180

# Predeclared before any fold metrics are computed.
WALKFORWARD_DECLARATION = {
    "full_tape_split": "chronological bar-index 60/20/20 on data/XAUUSD_i_5m_phase38.parquet",
    "evaluation_window_split": "chronological bar-index 60/20/20 on the Phase 38 180-day scan frame",
    "train_frac": TRAIN_FRAC,
    "val_frac": VAL_FRAC,
    "oos_frac": OOS_FRAC,
    "shuffle": False,
    "optimization": False,
    "refit": False,
    "declared_before_metrics": True,
    "full_tape_pa_scan": "NOT_RUN_RUNTIME_BOUND — official RAW book is the persisted 180-day Phase 38 scan",
}

SENSITIVITY_DECLARATION = {
    "declared_before_metrics": True,
    "commission": "UNKNOWN — not invented",
    "swap": "not applied — historical UNKNOWN",
    "spread_base_pips": 2.5,
    "slippage_base_pips": 0.8,
    "source": "BacktestConfig defaults; MODELED/SCENARIO, not BROKER-OBSERVED",
    "scenarios": (
        {"id": "RAW_NO_COST", "spread_mult": 0.0, "slip_mult": 0.0},
        {"id": "MODELED_1X", "spread_mult": 1.0, "slip_mult": 1.0},
        {"id": "MODELED_2X", "spread_mult": 2.0, "slip_mult": 2.0},
        {"id": "MODELED_3X", "spread_mult": 3.0, "slip_mult": 3.0},
    ),
}

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "gap_matrix",
    "mt5",
    "symbols",
    "commission",
    "swap",
    "spread",
    "slippage",
    "execution",
    "cost_model_audit",
    "cost_completeness",
    "case",
    "raw_signal",
    "executable",
    "walk_forward",
    "events",
    "dependence",
    "cost_sensitivity",
    "statistics",
    "comparison",
    "FINAL_GATE",
    "phase_40_started",
)

FORBIDDEN_OUTPUT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("REDACTED" if str(k).lower() in FORBIDDEN_OUTPUT_KEYS else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def build_gap_matrix(prior38: dict[str, Any], prior35: dict[str, Any]) -> list[dict[str, Any]]:
    c38 = prior38.get("commission") or {}
    s38 = prior38.get("slippage") or {}
    sw38 = prior38.get("swap") or {}
    ex38 = prior38.get("execution") or {}
    return [
        {
            "evidence_id": "COMMISSION",
            "phase38_state": c38.get("status"),
            "required_state": "VERIFIED_SCHEDULE",
            "note": "Phase 38 gold deal zeros are not a verified schedule",
        },
        {
            "evidence_id": "SWAP",
            "phase38_state": sw38.get("classification"),
            "required_state": "OBSERVED_HISTORICAL or documented BROKER_RATE_ONLY",
            "note": "current rates ≠ historical series",
        },
        {
            "evidence_id": "SPREAD_BIDASK",
            "phase38_state": (prior38.get("bid_ask") or {}).get("status"),
            "required_state": "OBSERVED historical Bid/Ask on evaluation tape",
            "note": "27.26 sidecar is ~15d on frozen tape only",
        },
        {
            "evidence_id": "SLIPPAGE",
            "phase38_state": s38.get("status"),
            "required_state": "genuine requested vs filled pairs on XAUUSD_i",
            "note": "deal.price / price_open / deviation are not requested",
        },
        {
            "evidence_id": "EXECUTION",
            "phase38_state": ex38.get("grade"),
            "required_state": "FULL_EXECUTION_EVIDENCE",
            "note": "Phase 38 DEAL_FILL_TAPE_ONLY",
        },
        {
            "evidence_id": "SYMBOL_BINDING",
            "phase38_state": prior38.get("ev_eq_01"),
            "required_state": "EV-EQ-01 proven or remain NOT_PROVEN",
            "note": "XAUUSD not observed on this terminal",
        },
        {
            "evidence_id": "COST_AND_GATE",
            "phase38_state": (prior38.get("cost_completeness") or {}).get("classification"),
            "required_state": "COMPLETE / cost_ready_for_validation True",
            "note": str((prior35.get("cost_completeness") or prior38.get("cost_completeness") or {}).get("classification")),
        },
    ]


def inspect_history(mt5: Any) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(HISTORY_START, end) or []
    orders = mt5.history_orders_get(HISTORY_START, end) or []
    gold_deals = [d for d in deals if is_gold_symbol(str(getattr(d, "symbol", "") or ""))]
    gold_orders = [o for o in orders if is_gold_symbol(str(getattr(o, "symbol", "") or ""))]
    xi_deals = [d for d in gold_deals if str(getattr(d, "symbol", "")) == CANONICAL_SYMBOL]
    commissions = [float(getattr(d, "commission", 0) or 0) for d in xi_deals]
    swaps = [float(getattr(d, "swap", 0) or 0) for d in xi_deals]
    hold_hours = []
    for d in xi_deals:
        t = getattr(d, "time", None)
        t_msc = getattr(d, "time_msc", None)
        if t is not None:
            hold_hours.append(None)
    vol_init = []
    vol_cur = []
    states = Counter()
    types = Counter()
    for o in gold_orders[:MAX_HISTORY_DETAIL]:
        states[ORDER_STATE_LABEL.get(int(getattr(o, "state", -1) or -1), str(getattr(o, "state", UNKNOWN)))] += 1
        types[ORDER_TYPE_LABEL.get(int(getattr(o, "type", -1) or -1), str(getattr(o, "type", UNKNOWN)))] += 1
        vol_init.append(float(getattr(o, "volume_initial", 0) or 0))
        vol_cur.append(float(getattr(o, "volume_current", 0) or 0))
    deal_entries = Counter()
    deal_types = Counter()
    for d in xi_deals[:MAX_HISTORY_DETAIL]:
        deal_entries[DEAL_ENTRY_LABEL.get(int(getattr(d, "entry", -1) or -1), str(getattr(d, "entry", UNKNOWN)))] += 1
        deal_types[DEAL_TYPE_LABEL.get(int(getattr(d, "type", -1) or -1), str(getattr(d, "type", UNKNOWN)))] += 1
    volume_mismatches = sum(1 for a, b in zip(vol_init, vol_cur) if abs(a - b) > 1e-9 and b > 0)
    partials = sum(1 for a, b in zip(vol_init, vol_cur) if b > 0 and abs(a - b) > 1e-9)
    nonzero_swap = [v for v in swaps if abs(v) > 1e-9]
    return {
        "deals_total": int(len(deals)),
        "orders_total": int(len(orders)),
        "gold_deals": int(len(gold_deals)),
        "xauusd_i_deals": int(len(xi_deals)),
        "gold_orders": int(len(gold_orders)),
        "commission_values_xi": commissions[:50],
        "all_xi_commission_zero": bool(commissions) and all(abs(v) < 1e-12 for v in commissions),
        "swap_values_xi": swaps[:50],
        "nonzero_swap_count": int(len(nonzero_swap)),
        "swap_nonzero_values": [round(v, 6) for v in nonzero_swap[:20]],
        "order_states": dict(states),
        "order_types": dict(types),
        "deal_entries": dict(deal_entries),
        "deal_types": dict(deal_types),
        "volume_initial_vs_current_nonzero_current": volume_mismatches,
        "possible_partials": partials,
        "requested_price_on_deal": False,
        "price_open_is_requested": False,
        "deviation_is_realized_slippage": False,
        "genuine_requested_vs_filled_pairs": 0,
        "positions_touched": False,
        "orders_modified": False,
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


def bounded_tick_probe(exe: str | None) -> dict[str, Any]:
    """Isolated subprocess so a hung copy_ticks cannot stall Phase 39."""
    code = (
        "import json,sys\n"
        "from datetime import datetime,timedelta,timezone\n"
        "try:\n"
        " import MetaTrader5 as mt5\n"
        "except Exception as e:\n"
        " print(json.dumps({'status':'BLOCKED','error':str(e)})); raise SystemExit(0)\n"
        "path=sys.argv[1] if len(sys.argv)>1 and sys.argv[1] not in ('None','') else None\n"
        "ok=bool(mt5.initialize(path=path, timeout=10000) if path else mt5.initialize())\n"
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
            [sys.executable, "-c", code, str(exe or "")],
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
    payload["not_ohlc_proxy"] = True
    payload["evaluation_tape_coverage"] = False
    return payload


def classify_commission(history: dict[str, Any], journal: dict[str, Any]) -> dict[str, Any]:
    zeros = bool(history.get("all_xi_commission_zero"))
    n = int(history.get("xauusd_i_deals") or 0)
    return {
        "status": "UNKNOWN",
        "classification": OBSERVED_ZERO_NOT_PROVEN if zeros and n else "UNKNOWN",
        "verified_schedule": False,
        "policy_gate": COMMISSION_POLICY,
        "zero_is_not_verified": True,
        "xauusd_i_deals": n,
        "all_observed_zeros": zeros,
        "account_product_type": UNKNOWN,
        "journal_does_not_verify_schedule": True,
        "journal": {"xauusd_i_pairs": journal.get("xauusd_i_requested_fill_pairs")},
        "note": (
            "Observed commission=0 on historical XAUUSD_i deals is OBSERVED_ZERO_NOT_PROVEN. "
            "No account-applicable LiteFinance-MT5-Live schedule was verified. "
            "Status remains UNKNOWN for the AND-gate."
        ),
    }


def classify_swap(xi: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    current_long = xi.get("swap_long")
    current_short = xi.get("swap_short")
    nonzero = int(history.get("nonzero_swap_count") or 0)
    if nonzero > 0:
        hist = "OBSERVED_HISTORICAL"
        note = "At least one XAUUSD_i deal has non-zero swap. That is charged-swap evidence, not a historical rate series."
    else:
        hist = "UNKNOWN"
        note = "Zero swap on observed deals does not prove historical swap is zero (holds may be intra-day)."
    return {
        "classification": "BROKER_RATE_ONLY",
        "current_broker_rate": "OBSERVED" if current_long not in (None, UNKNOWN) else UNKNOWN,
        "current_swap_long": current_long,
        "current_swap_short": current_short,
        "swap_rollover3days": xi.get("swap_rollover3days") or xi.get("rollover3days"),
        "observed_historical": hist,
        "inferred_historical": "NOT_INFERRED",
        "nonzero_historical_swap_deals": nonzero,
        "deal_zeros_prove_historical_zero": False,
        "note": note,
    }


def classify_slippage(history: dict[str, Any], journal: dict[str, Any]) -> dict[str, Any]:
    pairs = int(history.get("genuine_requested_vs_filled_pairs") or 0) + int(journal.get("xauusd_i_requested_fill_pairs") or 0)
    return {
        "status": "MODELED" if pairs == 0 else "PARTIAL",
        "genuine_requested_vs_executed_pairs": pairs,
        "mt5_deviation_is_realized_slippage": False,
        "price_open_is_requested": False,
        "deal_price_is_requested": False,
        "journal_logical_xauusd_live_pairs": journal.get("logical_xauusd_live_pairs"),
        "journal_mapped_to_xauusd_i": False,
        "reason": (
            "Live adapter stores request['price'] as requested_price in TradeJournal, but "
            "no XAUUSD_i journal pairs were found. Logical XAUUSD live rows are not used "
            "(EV-EQ-01 NOT_PROVEN). MT5 history_orders.price_open is not treated as requested."
        ),
    }


def classify_execution(history: dict[str, Any]) -> dict[str, Any]:
    deals = int(history.get("xauusd_i_deals") or 0)
    orders = int(history.get("gold_orders") or 0)
    if deals and orders:
        grade = "PARTIAL_EXECUTION_EVIDENCE"
    elif deals:
        grade = "DEAL_FILL_TAPE_ONLY"
    else:
        grade = "NOT_OBSERVED"
    return {
        "grade": grade,
        "deals": history.get("deals_total"),
        "orders": history.get("orders_total"),
        "xauusd_i_deals": deals,
        "gold_orders": orders,
        "order_states": history.get("order_states"),
        "possible_partials": history.get("possible_partials"),
        "requotes": UNKNOWN,
        "latency": UNKNOWN,
        "requested_vs_executed_price": "NOT_IDENTIFIABLE",
        "requested_vs_executed_volume": (
            "PARTIAL_FROM_VOLUME_INITIAL_CURRENT" if history.get("possible_partials") else "NOT_IDENTIFIABLE"
        ),
        "positions_touched": False,
        "orders_modified": False,
        "code_request_dict_has_price": True,
        "code_request_price_note": "Mt5ExecutionAdapter request['price'] is the live send price; historical MT5 objects do not retain it as a distinct requested field.",
    }


def evaluate_and_gate(
    *,
    attached: bool,
    xi_present: bool,
    ticks: dict[str, Any],
    commission: dict[str, Any],
    swap: dict[str, Any],
    slippage: dict[str, Any],
    execution: dict[str, Any],
    sidecar_exists: bool,
) -> dict[str, Any]:
    overlay = {
        "symbol_binding": {"status": "BLOCKED", "note": "EV-EQ-01 NOT_PROVEN; empty map; not weakened"},
        "economics": {
            "status": "PARTIAL" if attached and xi_present else "UNKNOWN",
            "note": "current symbol_info snapshot is not a historical economics series",
        },
        "dataset_provenance": {
            "status": "PARTIAL",
            "note": "phase38 XAUUSD_i M5 is a new research tape, ohlc_only PROXY sidecar; not production",
        },
        "spread": {
            "status": "BLOCKED",
            "note": (
                "evaluation tape has no Bid/Ask columns; 27.26 sidecar does not cover 1291d; "
                f"tick probe={ticks.get('status')}"
            ),
        },
        "commission": {
            "status": "BLOCKED",
            "note": "OBSERVED_ZERO_NOT_PROVEN; VERIFIED_SCHEDULE not met",
        },
        "swap": {
            "status": "UNKNOWN",
            "note": f"current rates {swap.get('current_broker_rate')}; historical {swap.get('observed_historical')}",
        },
        "slippage": {
            "status": "UNKNOWN",
            "note": f"{slippage.get('status')}; genuine pairs={slippage.get('genuine_requested_vs_executed_pairs')}",
        },
        "execution_model": {
            "status": "UNKNOWN",
            "note": execution.get("grade"),
        },
    }
    ready = cost_ready_for_validation({k: {"status": v["status"]} for k, v in overlay.items()})
    complete = sum(1 for v in overlay.values() if component_is_complete(v["status"]))
    return {
        "components": overlay,
        "complete_count": complete,
        "required_count": len(GATE_COMPONENTS),
        "cost_ready_for_validation": ready,
        "gate_weakened": False,
        "classification": "COMPLETE" if ready else "INCOMPLETE",
        "sidecar_27_26_exists": sidecar_exists,
        "COMPLETE_token": CostCompleteness.COMPLETE.value,
    }


def decide_case(*, ready: bool, events: int, days: float) -> dict[str, Any]:
    if ready:
        case = "A"
        reason = "All eight AND-gate components COMPLETE."
    elif events >= MIN_EVENTS and days >= 60:
        case = "B"
        reason = (
            "Cost gate incomplete, but the Phase 38 tape and event floor support a labeled "
            "MODELED cost-sensitivity analysis. Commission remains UNKNOWN and is not invented."
        )
    else:
        case = "C"
        reason = "Too incomplete for cost-adjusted or sensitivity conclusions."
    return {"case": case, "reason": reason, "forced_A": False}


def _perf(rows: list[dict[str, Any]], days: float) -> dict[str, Any]:
    ny_days = len({str(_parse_ts(r.get("timestamp")).date()) for r in rows if _parse_ts(r.get("timestamp"))})
    adapted = []
    for r in rows:
        adapted.append(
            {
                **r,
                "direction": r.get("side") or r.get("direction"),
                "theoretical_R": r.get("theoretical_R", r.get("r_multiple")),
                "r_multiple": r.get("theoretical_R", r.get("r_multiple")),
            }
        )
    return expand_raw_metrics(adapted, calendar_days=days, ny_session_days=max(ny_days, 1))


def apply_modeled_cost(row: dict[str, Any], *, spread_pips: float, slip_pips: float) -> float | None:
    """Round-trip MODELED spread (full width) + slippage both legs, in R. Commission not applied."""
    r0 = row.get("r_multiple")
    if r0 is None:
        return None
    entry = row.get("entry_price")
    sl = row.get("stop_loss")
    try:
        risk = abs(float(entry) - float(sl))
    except (TypeError, ValueError):
        return None
    if risk <= 0:
        return None
    pip = pip_size(PRIMARY_SYMBOL)
    round_trip = (float(spread_pips) + 2.0 * float(slip_pips)) * pip
    return float(r0) - (round_trip / risk)


def strategy_research(root: Path, m5: pd.DataFrame) -> dict[str, Any]:
    setups_blob = _safe_load_json(root / PHASE38_SETUPS) or {}
    setups = list(setups_blob.get("setups") or [])
    p38 = _safe_load_json(root / PHASE38_JSON) or {}
    if m5 is None or m5.empty:
        return {"ran": False, "reason": "phase38 M5 tape missing"}
    idx = pd.to_datetime(m5.index, utc=True)
    n = int(len(m5))
    full_splits = chronological_index_splits(n)
    full_split_ts = {}
    for name, sp in full_splits.items():
        a, b = int(sp["start_index"]), int(sp["end_index"])
        full_split_ts[name] = {
            **sp,
            "start_ts": str(idx[min(a, n - 1)]),
            "end_ts": str(idx[min(max(b - 1, a), n - 1)]),
            "rows": max(b - a, 0),
        }
    end = idx.max()
    eval_start = end - pd.Timedelta(days=EVAL_DAYS)
    eval_frame = m5.loc[idx >= eval_start]
    eval_n = int(len(eval_frame))
    eval_splits = chronological_index_splits(eval_n) if eval_n >= 3 else {}
    eval_idx = pd.to_datetime(eval_frame.index, utc=True)
    cfg = get_price_action_config(PRIMARY_SYMBOL, "M5")
    # Reconstruct Asian range on the evaluation frame using official function.
    if setups:
        from tradingbot.backtest.phase26c_zero_signal_audit import _enrich_frame

        enriched = _enrich_frame(eval_frame)
        setups = _attach_official_asian_range(setups, enriched, symbol=PRIMARY_SYMBOL)
    rows = []
    for i, s in enumerate(setups):
        row = dict(s)
        row["signal_id"] = row.get("signal_id") or f"P38-{i+1:04d}"
        row["theoretical_R"] = row.get("r_multiple")
        row["side"] = row.get("side") or row.get("direction")
        if row.get("asian_high") is None or row.get("asian_low") is None:
            continue
        rows.append(row)
    labeled = assign_mechanical_events(rows) if rows else []
    for r in labeled:
        r["event_cluster_id"] = r.get("mechanical_event_id")
        ts = _parse_ts(r.get("timestamp"))
        if ts is not None and eval_n >= 3:
            loc = int(eval_idx.get_indexer([ts], method="nearest")[0])
            for name, sp in eval_splits.items():
                if int(sp["start_index"]) <= loc < int(sp["end_index"]):
                    r["eval_fold"] = name
                    break
            else:
                r["eval_fold"] = "OOS"
        else:
            r["eval_fold"] = "UNKNOWN"
        if ts is not None:
            floc = int(idx.get_indexer([ts], method="nearest")[0])
            r["full_tape_fold"] = "OOS"
            for name, sp in full_splits.items():
                if int(sp["start_index"]) <= floc < int(sp["end_index"]):
                    r["full_tape_fold"] = name
                    break
    metrics = event_metrics(labeled) if labeled else {"event_count": 0, "signal_count": 0}
    for r in labeled:
        r["event_cluster_id"] = r.get("mechanical_event_id")
    reps = event_representatives(labeled) if labeled else []
    eval_days = float((eval_idx.max() - eval_idx.min()).total_seconds() / 86400.0) if eval_n else 0.0
    raw_perf = _perf(labeled, eval_days) if labeled else {}
    event_perf = _perf(reps, eval_days) if reps else {}
    folds = {}
    for name in ("TRAIN", "VALIDATION", "OOS"):
        subset = [r for r in labeled if r.get("eval_fold") == name]
        eids = {r.get("mechanical_event_id") for r in subset}
        folds[name] = {
            "signals": len(subset),
            "events": len(eids),
            "performance": _perf(subset, eval_days * (0.6 if name == "TRAIN" else 0.2)) if subset else None,
            "event_floor_met": len(eids) >= MIN_EVENTS,
        }
    full_fold_counts = Counter(r.get("full_tape_fold") for r in labeled)
    exe = ((p38.get("strategy_evaluation") or {}).get("executable") or {})
    cfg_bt = BacktestConfig()
    scenarios = []
    for spec in SENSITIVITY_DECLARATION["scenarios"]:
        sp = float(cfg_bt.spread_pips) * float(spec["spread_mult"])
        slp = float(cfg_bt.slippage_pips) * float(spec["slip_mult"])
        adjusted = []
        for r in reps:
            val = apply_modeled_cost(r, spread_pips=sp, slip_pips=slp) if spec["spread_mult"] or spec["slip_mult"] else r.get("r_multiple")
            if val is None:
                continue
            adjusted.append(val)
        scenarios.append(
            {
                "id": spec["id"],
                "class": "RAW" if spec["id"] == "RAW_NO_COST" else "SCENARIO_MODELED",
                "spread_pips": sp,
                "slippage_pips": slp,
                "commission": "UNKNOWN_NOT_APPLIED",
                "n": len(adjusted),
                "expectancy_R": (sum(adjusted) / len(adjusted)) if adjusted else None,
                "not_broker_observed": spec["id"] != "RAW_NO_COST",
            }
        )
    event_r = [float(r["r_multiple"]) for r in reps if r.get("r_multiple") is not None]
    rng = np.random.default_rng(RNG_SEED)
    boot = None
    if len(event_r) >= 2:
        paths = run_bootstrap(event_r, rng, N_PATHS)
        boot = summarize_paths(paths)
        boot["unit"] = "event-level theoretical R; clustered signals not treated as independent"
        boot["n_events"] = len(event_r)
        boot["n_paths"] = N_PATHS
        boot["seed"] = RNG_SEED
    oos_events = int(folds.get("OOS", {}).get("events") or 0)
    return {
        "ran": True,
        "dataset": PHASE38_M5,
        "logical_xauusd_used": False,
        "parameters_changed": False,
        "optimized": False,
        "evaluation_window_days": eval_days,
        "evaluation_rows": eval_n,
        "full_tape_days": float((idx.max() - idx.min()).total_seconds() / 86400.0),
        "full_tape_rows": n,
        "walkforward_declaration": WALKFORWARD_DECLARATION,
        "full_tape_splits": full_split_ts,
        "full_tape_setup_fold_counts": dict(full_fold_counts),
        "full_tape_strategy_train_val": "NOT_OBSERVED — RAW book exists only in last 180d, which falls in full-tape OOS",
        "eval_splits": eval_splits,
        "raw_signal": {
            "book": "RAW_SIGNAL",
            "n": len(labeled),
            "performance": raw_perf,
            "cost_adjusted": False,
        },
        "executable": {
            "book": "EXECUTABLE",
            "mixed_with_raw": False,
            "ran": bool(exe.get("ran")),
            "candidates": exe.get("candidates"),
            "allowed": exe.get("allowed"),
            "rejected": exe.get("rejected"),
            "executed_simulated_trades": exe.get("executed_simulated_trades"),
            "rejection_reasons": exe.get("rejection_reasons"),
            "note": exe.get("broker_fill_note") or "Phase 38 RiskGate replay reused; commission UNKNOWN fail-closes fills.",
        },
        "events": {
            "definition": "(UTC date, asian_high, asian_low, side)",
            "count": int(metrics.get("event_count") or 0),
            "signals": int(metrics.get("signal_count") or 0),
            "signals_per_event_mean": (metrics.get("signals_per_event") or {}).get("mean"),
            "floor_met": int(metrics.get("event_count") or 0) >= MIN_EVENTS,
            "independence_manufactured": False,
            "performance": event_perf,
            "representatives": "earliest timestamp per mechanical event",
        },
        "dependence": {
            "singleton_events": metrics.get("singleton_events"),
            "clustered_events": metrics.get("clustered_events"),
            "clustered_signal_share": metrics.get("clustered_signal_share"),
            "largest_cluster_signal_share": metrics.get("largest_cluster_signal_share"),
            "statistical_independence_claimed": False,
        },
        "walk_forward": {
            "evaluation_window_folds": folds,
            "oos_event_floor_met": oos_events >= MIN_EVENTS,
            "oos_events": oos_events,
            "train_validation_descriptive_only": True,
        },
        "cost_sensitivity": {
            "declaration": SENSITIVITY_DECLARATION,
            "unit": "event-level theoretical R minus MODELED round-trip spread+slippage",
            "scenarios": scenarios,
        },
        "statistics": {
            "event_bootstrap": boot,
            "signal_level_not_independent_evidence": True,
            "profitability_verdict": "NOT_ISSUED",
        },
    }


def cost_model_audit() -> dict[str, Any]:
    cfg = BacktestConfig()
    return {
        "implementation": "tradingbot/backtest/cost_model.py + BacktestConfig",
        "changed": False,
        "spread": {"config": cfg.spread_mode, "pips": cfg.spread_pips, "represents": "MODELED_PROXY / AUTO; not dataset Bid/Ask"},
        "commission": {"config": cfg.commission_status, "represents": "UNKNOWN fail-closed; zeros not inferred"},
        "swap": {"config": cfg.swap_status, "represents": "UNKNOWN / BROKER_RATE_ONLY ≠ historical series"},
        "slippage": {"config": cfg.slippage_status, "pips": cfg.slippage_pips, "represents": "MODELED_PROXY; not requested-vs-fill"},
        "execution": {"represents": "SimulatedBroker full-fill is not realized MT5 execution"},
        "favorable_unknown_replacement": False,
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    cmp_rows = "\n".join(
        f"| {r['evidence']} | {r['phase36']} | {r['phase38']} | {r['phase39']} | {r['status']} |"
        for r in payload.get("comparison") or []
    )
    cost = payload.get("cost_completeness") or {}
    comm = payload.get("commission") or {}
    sw = payload.get("swap") or {}
    sl = payload.get("slippage") or {}
    ex = payload.get("execution") or {}
    case = payload.get("case") or {}
    research = payload.get("research") or {}
    ev = research.get("events") or {}
    raw = (research.get("raw_signal") or {}).get("performance") or {}
    (root / PHASE39_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE39_MD).write_text(
        f"""# Phase 39 — Broker Economics + Execution Evidence Resolution

**STATUS:** `{payload.get("status")}`
**Class:** RESEARCH / EVIDENCE ONLY
**Case:** `{case.get("case")}` — {case.get("reason")}
**cost_ready_for_validation:** `{cost.get("cost_ready_for_validation")}`
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`
**Real account interaction:** `{payload.get("real_account_interaction")}`
**Frozen dataset changed:** `{False if payload.get("fingerprints", {}).get("phase28_m5_unchanged") else True}`
**Production changes:** `NONE`

STOP AFTER PHASE 39. DO NOT START PHASE 40.
DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.

This phase does **not** issue a profitability verdict.

---

## Answers

1. Broker evidence improved? **{payload.get("broker_evidence_improved")}**
2. cost_ready_for_validation? **{cost.get("cost_ready_for_validation")}**
3. Cost-adjusted broker-realistic performance? **{payload.get("cost_adjusted_broker_realistic")}**
4. XAUUSD_i dataset sufficient for final statistical research? **{payload.get("dataset_sufficient_for_final_stats")}**
5. Strategy still blocked? **YES** — FINAL_GATE BLOCKED
6. Remaining missing evidence: {payload.get("remaining_missing")}

## MT5

{(payload.get("mt5") or {})}

## Symbols

XAUUSD_i: `{(payload.get("symbols") or {}).get("XAUUSD_i", {}).get("existence")}`  
XAUUSD: `{(payload.get("symbols") or {}).get("XAUUSD", {}).get("existence")}`  
EV-EQ-01: `{payload.get("ev_eq_01")}`

Current XAUUSD_i economics timestamp: `{(payload.get("symbols") or {}).get("XAUUSD_i", {}).get("quote_utc")}`  
These are **current** broker fields, not a historical economics series.

## Commission / swap / spread / slippage / execution

- Commission: `{comm.get("classification")}` — verified_schedule=`{comm.get("verified_schedule")}`
- Swap: current `{sw.get("classification")}` / historical `{sw.get("observed_historical")}`
- Spread / Bid-Ask: `{(payload.get("spread") or {}).get("status")}`
- Slippage: `{sl.get("status")}` pairs=`{sl.get("genuine_requested_vs_executed_pairs")}`
- Execution grade: `{ex.get("grade")}`

## Cost AND-gate (not weakened)

Ready: `{cost.get("cost_ready_for_validation")}` · `{cost.get("complete_count")}/{cost.get("required_count")}` `{cost.get("classification")}`  
Gate weakened: `{cost.get("gate_weakened")}`

## Unchanged-strategy research (Phase 38 tape)

RAW n=`{(research.get("raw_signal") or {}).get("n")}` expectancy_R=`{raw.get("expectancy_R")}` PF=`{raw.get("profit_factor")}` WR=`{raw.get("win_rate")}` maxDD_R=`{raw.get("max_drawdown_R")}`  
Events: `{ev.get("count")}` · signals/event `{ev.get("signals_per_event_mean")}` · floor met `{ev.get("floor_met")}`  
EXECUTABLE allowed=`{(research.get("executable") or {}).get("allowed")}` fills=`{(research.get("executable") or {}).get("executed_simulated_trades")}`  
Independence claimed: `False`

Walk-forward: 60/20/20 declared on the 180-day evaluation frame. Full-tape PA scan was **not** re-run. Setups from the 180-day book fall in the full-tape OOS fold.

Sensitivity is **SCENARIO / MODELED**. Commission is **UNKNOWN_NOT_APPLIED**.

## Comparison

| Evidence | Phase 36 | Phase 38 | Phase 39 | Status |
|---|---|---|---|---|
{cmp_rows}

## Recommended next

{payload.get("recommended_next_phase")}

## Safety

No orders, no `.env`, no frozen parquet rewrite, no bot/daemon, no optimization, no ML activation.
Phase 40 was **not** started.
""",
        encoding="utf-8",
    )


def _patch_truth_docs(root: Path, *, status: str) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Broker economics execution (Phase 39)"
        block = (
            "\n\n## Broker economics execution (Phase 39)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            f"| Phase 39 status | **{status}** |\n"
            "| Frozen Phase 28/30 M5 overwritten | **NO** |\n"
            "| Silent XAUUSD map | **NO** |\n"
            "| cost_ready_for_validation | **FALSE** |\n"
            "| Profitability verdict | **NOT ISSUED** |\n"
            "| Phase 40 started | **NO** |\n"
        )
        if marker in text:
            start = text.find(marker)
            rest = text[start + len(marker) :]
            nxt = rest.find("\n## ")
            end = start + len(marker) + (nxt if nxt >= 0 else len(rest))
            text = text[:start].rstrip() + block + (text[end:] if nxt >= 0 else "")
            known.write_text(text, encoding="utf-8")
        else:
            known.write_text(text.rstrip() + block, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        row = (
            f"| Phase 39 broker economics | `run_phase39_collection()` | n/a | RESEARCH; cost/execution evidence + labeled sensitivity; no bot/orders/.env | **{status}**; Phase 40 not started |"
        )
        text = re.sub(r"\| Phase 39 broker economics \|.*\n", row + "\n", text)
        if "Phase 39 broker economics" not in text:
            needle = "| Phase 38 intelligent evidence |"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + row + "\n" + text[end + 1 :]
        cfg.write_text(text, encoding="utf-8")
    sot = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    if sot.is_file():
        text = sot.read_text(encoding="utf-8")
        para = (
            "Phase 39 (`docs_v2/02_research/PHASE39_BROKER_ECONOMICS_EXECUTION.md`) is research-only "
            "broker economics and execution evidence resolution on the Phase 38 XAUUSD_i tape. "
            "It does not authorize live trading, overwrite the frozen M5 snapshot, or start Phase 40.\n"
        )
        if "PHASE39_BROKER_ECONOMICS_EXECUTION.md" not in text:
            marker = "Phase 38 (`docs_v2/02_research/PHASE38_INTELLIGENT_EVIDENCE_ACQUISITION.md`)"
            idx = text.find(marker)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + "\n" + para + text[end + 1 :]
                sot.write_text(text, encoding="utf-8")
    boundary = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    if boundary.is_file():
        text = boundary.read_text(encoding="utf-8")
        line = (
            "`tradingbot/backtest/phase39_broker_economics_execution.py` — **RESEARCH_ONLY** "
            "broker economics/execution evidence; may attach identified MT5 read-only; does not overwrite Phase 28 M5.  \n"
        )
        if "phase39_broker_economics_execution.py" not in text:
            needle = "`tradingbot/backtest/phase38_intelligent_evidence_acquisition.py`"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + line + text[end + 1 :]
                boundary.write_text(text, encoding="utf-8")


def run_phase39_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    frozen_fp = file_fingerprint(root / CANONICAL_PARQUET)
    if frozen_fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Frozen Phase 28/30 M5 fingerprint changed — Phase 39 refuses to proceed")
    prior38 = _safe_load_json(root / PHASE38_JSON) or {}
    prior35 = _safe_load_json(root / PHASE35_JSON) or {}
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    gaps = build_gap_matrix(prior38, prior35)

    discovery = discover_mt5_installations()
    selection = select_relevant_terminal(discovery)
    selected_exe = ((selection.get("selected") or {}) or {}).get("terminal_exe") or PREFERRED_EXE
    launch = {"launched_by_phase": False, "already_running": terminal64_running(), "ok": False}
    attach: dict[str, Any] = {"ok": False, "status": "BLOCKED", "env_accessed": False}
    if selected_exe:
        launch = launch_terminal(selected_exe)
        if launch.get("ok"):
            if not launch.get("already_running"):
                time.sleep(8)
            attach = attach_with_path(selected_exe)
    attached = bool(attach.get("ok"))
    symbols = attach.get("symbols") or {
        CANONICAL_SYMBOL: {"existence": UNKNOWN},
        LOGICAL_SYMBOL: {"existence": "NOT_OBSERVED_ON_THIS_TERMINAL", "broker_wide_absence_concluded": False},
    }
    xi = dict(symbols.get(CANONICAL_SYMBOL) or {})
    xau = dict(symbols.get(LOGICAL_SYMBOL) or {})
    if xau.get("existence") in {"NO", "ABSENT_ON_OBSERVED_TERMINAL", None, UNKNOWN}:
        xau["existence"] = "NOT_OBSERVED_ON_THIS_TERMINAL"
        xau["broker_wide_absence_concluded"] = False

    history = {
        "deals_total": 0,
        "orders_total": 0,
        "xauusd_i_deals": 0,
        "genuine_requested_vs_filled_pairs": 0,
        "positions_touched": False,
        "orders_modified": False,
    }
    if attached:
        try:
            import MetaTrader5 as mt5

            history = inspect_history(mt5)
        except Exception as exc:
            history["error"] = str(exc)

    journal = inspect_journal(root)
    ticks = bounded_tick_probe(selected_exe if attached else None)
    sidecar = (root / BIDASK_SIDECAR).is_file()
    commission = classify_commission(history, journal)
    swap = classify_swap(xi, history)
    slippage = classify_slippage(history, journal)
    execution = classify_execution(history)
    spread = {
        "status": "PROXY / NOT_OBSERVED",
        "evaluation_tape_bid_ask": False,
        "tick_probe": ticks.get("status"),
        "tick_rows": ticks.get("rows"),
        "sidecar_27_26": BIDASK_SIDECAR if sidecar else None,
        "sidecar_covers_phase38_tape": False,
        "ohlc_proxy_relabeled_observed": False,
        "current_bid": xi.get("bid"),
        "current_ask": xi.get("ask"),
        "current_quote_is_historical_tape": False,
    }
    if ticks.get("status") == "OBSERVED":
        spread["recent_ticks"] = "OBSERVED_BOUNDED_2MIN"
        spread["status"] = "PARTIAL - current/recent ticks only; evaluation tape remains PROXY"
    cost = evaluate_and_gate(
        attached=attached,
        xi_present=xi.get("existence") == "YES",
        ticks=ticks,
        commission=commission,
        swap=swap,
        slippage=slippage,
        execution=execution,
        sidecar_exists=sidecar,
    )
    audit = cost_model_audit()
    m5 = load_parquet_utc(root / PHASE38_M5) if (root / PHASE38_M5).is_file() else pd.DataFrame()
    days = float((m5.index.max() - m5.index.min()).total_seconds() / 86400.0) if len(m5) else 0.0
    research = strategy_research(root, m5)
    n_events = int((research.get("events") or {}).get("count") or 0)
    case = decide_case(ready=bool(cost["cost_ready_for_validation"]), events=n_events, days=days)

    comparison = [
        {"evidence": "M5 horizon", "phase36": "~14.88d", "phase38": "1291.4d", "phase39": f"{days:.2f}d reused", "status": "MET_PREFERRED"},
        {"evidence": "M15", "phase36": "none", "phase38": "OBSERVED", "phase39": "reused", "status": "OBSERVED"},
        {"evidence": "mechanical events", "phase36": "6", "phase38": "43", "phase39": str(n_events), "status": "SUFFICIENT" if n_events >= MIN_EVENTS else "INSUFFICIENT"},
        {"evidence": "symbol binding", "phase36": "NOT_PROVEN", "phase38": "NOT_PROVEN", "phase39": "NOT_PROVEN", "status": "NOT_PROVEN"},
        {"evidence": "symbol economics", "phase36": "UNKNOWN/PARTIAL", "phase38": "CURRENT_SNAPSHOT", "phase39": "CURRENT_SNAPSHOT", "status": "PARTIAL"},
        {"evidence": "spread", "phase36": "PROXY", "phase38": "NOT_OBSERVED", "phase39": spread.get("status"), "status": "BLOCKED"},
        {"evidence": "commission", "phase36": "UNKNOWN", "phase38": "UNKNOWN", "phase39": commission.get("classification"), "status": "UNKNOWN"},
        {"evidence": "swap", "phase36": "BROKER_RATE_ONLY", "phase38": "BROKER_RATE_ONLY", "phase39": swap.get("classification"), "status": "BROKER_RATE_ONLY"},
        {"evidence": "slippage", "phase36": "MODELED", "phase38": "MODELED", "phase39": slippage.get("status"), "status": "MODELED"},
        {"evidence": "execution", "phase36": "DEAL_FILL_TAPE_ONLY", "phase38": "DEAL_FILL_TAPE_ONLY", "phase39": execution.get("grade"), "status": execution.get("grade")},
        {"evidence": "cost AND-gate", "phase36": "0/8", "phase38": "0/8", "phase39": f"{cost['complete_count']}/8", "status": cost["classification"]},
        {"evidence": "statistical sufficiency", "phase36": "INSUFFICIENT", "phase38": "EVENT_SAMPLE_MET", "phase39": "EVENT_SAMPLE_MET" if n_events >= MIN_EVENTS else "INSUFFICIENT", "status": "EVENT_SAMPLE_MET_NOT_SIGNIFICANCE"},
        {"evidence": "OOS sufficiency", "phase36": "no", "phase38": "not split", "phase39": f"eval OOS events={(research.get('walk_forward') or {}).get('oos_events')}", "status": "INSUFFICIENT" if not (research.get("walk_forward") or {}).get("oos_event_floor_met") else "MET"},
    ]
    broker_improved = execution.get("grade") in {"PARTIAL_EXECUTION_EVIDENCE", "FULL_EXECUTION_EVIDENCE"} or int(history.get("nonzero_swap_count") or 0) > 0
    remaining = (
        "VERIFIED_SCHEDULE commission; historical swap series; Bid/Ask on the evaluation tape; "
        "XAUUSD_i requested-vs-fill pairs; EV-EQ-01; full-tape TRAIN/VAL RAW scan; OOS event floor"
    )
    env_label = str(attach.get("environment") or UNKNOWN)
    real_interaction = "READ_ONLY" if attached and env_label == "REAL" else ("NONE" if not attached else f"READ_ONLY_{env_label}")
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    ok_immut, issues = verify_immutability(before, base_dir=root)
    issues = [i for i in issues if "phase38" not in i and "phase39" not in i]
    binding = classify_dataset_binding(CANONICAL_SYMBOL, configured_symbol=PRIMARY_SYMBOL, dataset_symbol_map={})
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS" if attached else "PASS_WITH_DEFERRAL",
        "research_only": True,
        "production_changes": "NONE",
        "parameters_optimized": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "env_accessed": False,
        "silent_xauusd_mapping": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "real_account_interaction": real_interaction,
        "gap_matrix": gaps,
        "mt5": {
            "discovery": discovery,
            "selection": selection,
            "launch": launch,
            "attach": {k: v for k, v in attach.items() if k != "symbols"},
        },
        "symbols": {"XAUUSD_i": xi, "XAUUSD": xau},
        "commission": commission,
        "swap": swap,
        "spread": spread,
        "slippage": slippage,
        "execution": execution,
        "ticks": ticks,
        "journal": journal,
        "history": {k: v for k, v in history.items() if k not in {"commission_values_xi", "swap_values_xi"} or True},
        "cost_model_audit": audit,
        "cost_completeness": cost,
        "case": case,
        "dataset_binding": {
            "canonical_symbol": CANONICAL_SYMBOL,
            "dataset_symbol_map": {},
            "empty_map": True,
            "xauusd_merged": False,
            "ev_eq_01": "NOT_PROVEN",
            "binding": binding.to_dict(),
        },
        "research": research,
        "raw_signal": research.get("raw_signal"),
        "executable": research.get("executable"),
        "walk_forward": research.get("walk_forward"),
        "events": research.get("events"),
        "dependence": research.get("dependence"),
        "cost_sensitivity": research.get("cost_sensitivity"),
        "statistics": research.get("statistics"),
        "comparison": comparison,
        "broker_evidence_improved": "YES" if broker_improved else "PARTIAL/NO — economics refreshed; schedule still unverified",
        "cost_adjusted_broker_realistic": False,
        "dataset_sufficient_for_final_stats": False,
        "remaining_missing": remaining,
        "recommended_next_phase": (
            "Do not start Phase 40 automatically. Remaining work is operator/broker evidence: "
            "account-applicable commission schedule, historical Bid/Ask for the evaluation tape, "
            "and genuine XAUUSD_i request/fill pairs. Do not optimize. Do not trade."
        ),
        "fingerprints": {
            "phase28_m5_file": frozen_fp,
            "phase28_m5_unchanged": fp_after == frozen_fp == EXPECTED_CANONICAL_FINGERPRINT,
            "phase38_m5_file": file_fingerprint(root / PHASE38_M5) if (root / PHASE38_M5).is_file() else None,
        },
        "datasets_changed": fp_after != frozen_fp,
        "immutability_ok": len(issues) == 0 and fp_after == frozen_fp,
        "immutability_issues": issues,
        "safety": {
            "MT5_LAUNCHED_BY_PHASE": bool(launch.get("launched_by_phase")),
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "CANONICAL_M5_OVERWRITTEN": False,
            "SILENT_XAUUSD_MAP": False,
            "PRODUCTION_CHANGED": False,
            "PHASE_40_STARTED": False,
        },
        "phase_40_started": False,
        "next_step": "STOP. Do not start Phase 40. Do not optimize. Do not trade.",
    }
    payload = _redact(payload)
    _write_json(root / PHASE39_JSON, payload)
    _write_markdown(root, payload)
    _patch_truth_docs(root, status=str(payload["status"]))
    if file_fingerprint(root / CANONICAL_PARQUET) != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Phase 39 mutated the frozen canonical M5 parquet")
    return payload


if __name__ == "__main__":
    run_phase39_collection()
