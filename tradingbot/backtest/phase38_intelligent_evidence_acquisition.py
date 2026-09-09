"""Phase 38 — intelligent evidence acquisition (research / data only).

May launch an identified installed MT5 terminal. Does not start the bot,
send orders, read .env, silently map XAUUSD, overwrite the frozen Phase 28
snapshot, optimize, or change production.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from engine.strategies.price_action_strategy import PriceActionStrategy
from tradingbot.adapters.legacy_loader import load_legacy_config

from tradingbot.adapters.mt5_utils import (
    _read_common_ini_fields,
    _terminal_data_dirs,
    _terminal_exe_from_data_dir,
)
from tradingbot.backtest.dataset_contract import classify_dataset_binding
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase26c_zero_signal_audit import WARMUP, _append_forming_bar_m5, _enrich_frame
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    UNKNOWN,
    account_identity_snapshot,
    catalog_existence_check,
    login_identity_hash,
    terminal64_running,
    terminal_build_snapshot,
)
from tradingbot.backtest.phase27_15_cost_completeness_gate import (
    GATE_COMPONENTS,
    component_is_complete,
    cost_ready_for_validation,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    H4_CONTEXT_PARQUET,
    _build_research_engine,
    build_research_configuration,
    evaluate_executable_edge,
    load_parquet_utc,
    theoretical_outcome,
)
from tradingbot.backtest.phase29_research_tape import content_fingerprint
from tradingbot.backtest.phase31_event_independence import (
    assign_mechanical_events,
    event_metrics,
)
from tradingbot.backtest.phase35_execution_reality import PHASE35_JSON
from tradingbot.backtest.phase37_long_horizon_tape import (
    CANONICAL_SYMBOL,
    LOGICAL_SYMBOL,
    MIN_DAYS,
    TARGET_DAYS,
    _enrich_symbol,
    audit_dataset,
    collect_ohlc_chunked,
    collect_ticks_bounded,
    spread_stats,
    strategy_window_coverage,
    write_research_parquet,
    _ticks_to_bidask,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import apply_pa_to_legacy, get_price_action_config
from tradingbot.domain.gold_strategies.m5_london_sweep import asian_range, m5_asian_end_hour, m5_ny_entry_hours
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.domain.pa_hardening import clear_pa_dedup_cache

PHASE = "38"
PHASE38_JSON = "logs/phase38_intelligent_evidence_acquisition.json"
PHASE38_MD = "docs_v2/02_research/PHASE38_INTELLIGENT_EVIDENCE_ACQUISITION.md"
PHASE38_M5 = "data/XAUUSD_i_5m_phase38.parquet"
PHASE38_M15 = "data/XAUUSD_i_m15_phase38.parquet"
PHASE38_M1 = "data/XAUUSD_i_m1_phase38.parquet"
PHASE38_TICKS = "data/XAUUSD_i_ticks_phase38.parquet"
PHASE38_BIDASK = "logs/phase38_xauusd_i_bidask.parquet"
PHASE38_SETUPS = "logs/phase38_raw_setups.json"
PREFERRED_SERVER_TOKEN = "litefinance"
PREFERRED_EXE = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LAUNCH_WAIT_SEC = 90
HISTORY_DAYS = 90
HISTORY_LOOKBACK_START = datetime(2018, 1, 1, tzinfo=timezone.utc)
MAX_HISTORY_ROWS = 200
MIN_EVENTS = 30
SCAN_DAYS = 180
PHASE38_RESEARCH_FILES = (
    "XAUUSD_i_5m_phase38.parquet",
    "XAUUSD_i_m15_phase38.parquet",
    "XAUUSD_i_m1_phase38.parquet",
    "XAUUSD_i_ticks_phase38.parquet",
)
EXTRA_SYMBOL_ATTRS = (
    ("description", "description"),
    ("currency_base", "currency_base"),
    ("currency_profit", "currency_profit"),
    ("currency_margin", "currency_margin"),
    ("spread", "spread"),
    ("trade_contract_size", "trade_contract_size"),
    ("trade_tick_size", "trade_tick_size"),
    ("trade_tick_value", "trade_tick_value"),
    ("trade_tick_value_profit", "trade_tick_value_profit"),
    ("trade_tick_value_loss", "trade_tick_value_loss"),
    ("trade_mode", "trade_mode"),
    ("trade_exemode", "trade_exemode"),
    ("filling_mode", "filling_mode"),
    ("stops_level", "trade_stops_level"),
    ("freeze_level", "trade_freeze_level"),
    ("swap_rollover3days", "swap_rollover3days"),
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "gap_matrix",
    "mt5_discovery",
    "symbols",
    "m5",
    "bid_ask",
    "commission",
    "swap",
    "slippage",
    "execution",
    "dataset_binding",
    "cost_completeness",
    "event_sufficiency",
    "strategy_evaluation",
    "comparison",
    "FINAL_GATE",
    "phase_39_started",
)

EVIDENCE_IDS = (
    "DATA_M5_LONG_HORIZON",
    "DATA_M15",
    "DATA_M1",
    "DATA_TICKS",
    "BID_ASK",
    "SYMBOL_ECONOMICS",
    "COMMISSION",
    "SWAP",
    "SLIPPAGE",
    "ORDER_HISTORY",
    "DEAL_HISTORY",
    "REQUESTED_VS_FILLED",
    "EXECUTION_BEHAVIOR",
    "SYMBOL_BINDING",
)

BLOCKED_LOGICAL_TAPES = (
    "data/backtest/XAUUSD_M5_183d.parquet",
    "data/backtest/XAUUSD_M5_180d.parquet",
    "data/cache/XAUUSD_M5_180d.parquet",
    "data/XAUUSD_5m.parquet",
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


def _origin_text(data_dir: Path) -> str | None:
    origin = data_dir / "origin.txt"
    if not origin.is_file():
        return None
    raw = origin.read_bytes()
    for enc in ("utf-16-le", "utf-8", "utf-16"):
        try:
            text = raw.decode(enc).replace("\ufeff", "").strip()
            if text:
                return text
        except Exception:
            continue
    return None


def discover_mt5_installations() -> dict[str, Any]:
    """Filesystem discovery only. Does not read .env or credentials."""
    glob_hits = []
    for pattern in (
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
        r"C:\Program Files\LiteFinance*\terminal64.exe",
        r"C:\Program Files (x86)\LiteFinance*\terminal64.exe",
        r"C:\Program Files\*LiteFinance*\terminal64.exe",
    ):
        glob_hits.extend(glob.glob(pattern))
    data_dirs = []
    for data_dir in _terminal_data_dirs():
        hint = _read_common_ini_fields(data_dir / "config" / "common.ini")
        origin = _origin_text(data_dir)
        exe = _terminal_exe_from_data_dir(data_dir)
        if not exe and origin:
            cand = Path(origin)
            if cand.is_dir():
                cand = cand / "terminal64.exe"
            if cand.is_file():
                exe = str(cand)
        data_dirs.append(
            {
                "data_dir": str(data_dir),
                "origin": origin,
                "terminal_exe": exe,
                "saved_server": hint.get("saved_server"),
                "login_identity": login_identity_hash(hint.get("saved_login")),
                "experts_api_enabled": hint.get("experts_api_enabled"),
                "litefinance_server": bool(
                    hint.get("saved_server") and PREFERRED_SERVER_TOKEN in str(hint.get("saved_server")).lower()
                ),
            }
        )
    running = terminal64_running()
    return {
        "glob_hits": glob_hits,
        "data_dirs": data_dirs,
        "terminal64_running": running,
        "installed": bool(glob_hits) or any(d.get("terminal_exe") for d in data_dirs),
    }


def select_relevant_terminal(discovery: dict[str, Any]) -> dict[str, Any]:
    """Prefer LiteFinance Live / Program Files MetaTrader 5 from project evidence. Do not pick FIBO."""
    ranked: list[dict[str, Any]] = []
    for row in discovery.get("data_dirs") or []:
        exe = row.get("terminal_exe")
        if not exe:
            continue
        path = str(exe)
        if "fibo" in path.lower():
            row = {**row, "rejected": "OTHER_BROKER_NOT_PROJECT_LITEFINANCE"}
            ranked.append(row)
            continue
        score = 0
        if row.get("litefinance_server"):
            score += 100
        if path.lower().replace("/", "\\") == PREFERRED_EXE.lower():
            score += 50
        if "metatrader 5" in path.lower():
            score += 10
        ranked.append({**row, "score": score, "rejected": None})
    chosen = None
    for row in sorted((r for r in ranked if not r.get("rejected")), key=lambda r: r.get("score") or 0, reverse=True):
        if (row.get("score") or 0) > 0:
            chosen = row
            break
    if chosen is None and Path(PREFERRED_EXE).is_file():
        chosen = {
            "terminal_exe": PREFERRED_EXE,
            "saved_server": UNKNOWN,
            "litefinance_server": False,
            "score": 5,
            "note": "fallback to installed Program Files MetaTrader 5 executable",
        }
    return {
        "candidates": ranked,
        "selected": chosen,
        "reason": (
            "LiteFinance-MT5-Live / Program Files MetaTrader 5 from Phase 27 evidence"
            if chosen
            else "no project-relevant terminal executable identified"
        ),
        "mt5_not_installed": not discovery.get("installed"),
    }


def launch_terminal(exe: str) -> dict[str, Any]:
    meta = {
        "launched_by_phase": False,
        "already_running": False,
        "ok": False,
        "exe": exe,
        "error": None,
        "wait_sec": 0,
    }
    if terminal64_running():
        meta["already_running"] = True
        meta["ok"] = True
        return meta
    if not Path(exe).is_file():
        meta["error"] = "selected terminal executable is not a file"
        return meta
    try:
        subprocess.Popen(
            [exe],
            cwd=str(Path(exe).parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        meta["launched_by_phase"] = True
    except OSError as exc:
        meta["error"] = str(exc)
        return meta
    deadline = time.time() + LAUNCH_WAIT_SEC
    while time.time() < deadline:
        time.sleep(3)
        meta["wait_sec"] = int(LAUNCH_WAIT_SEC - max(deadline - time.time(), 0))
        if terminal64_running():
            meta["ok"] = True
            return meta
    meta["error"] = "terminal64.exe did not appear in process list after launch wait"
    return meta


def attach_with_path(exe: str) -> dict[str, Any]:
    session: dict[str, Any] = {
        "ok": False,
        "status": "NOT_ATTACHED",
        "attach_only": True,
        "credentials_used": False,
        "env_accessed": False,
        "symbol_select_called": False,
        "orders_sent": False,
        "error": None,
        "exe": exe,
        "auth_required": False,
    }
    try:
        import MetaTrader5 as mt5
    except ImportError:
        session["error"] = "MetaTrader5 package not installed"
        session["status"] = "BLOCKED"
        return session
    try:
        existing = mt5.terminal_info()
        if existing is not None and bool(getattr(existing, "connected", False)):
            session["ok"] = True
            session["status"] = "ATTACHED"
            session["method"] = "reuse already-connected session"
        else:
            initialized = bool(mt5.initialize(path=exe, timeout=30000))
            if not initialized:
                err = mt5.last_error()
                session["error"] = f"mt5.initialize(path=...) failed: {err}"
                code = err[0] if isinstance(err, tuple) and err else None
                if code in (-6, -10005):
                    session["auth_required"] = True
                    session["status"] = "AUTH_REQUIRED"
                else:
                    session["status"] = "NOT_ATTACHED"
                return session
            session["ok"] = True
            session["status"] = "ATTACHED"
            session["method"] = "initialize path-only; no login/password"
    except Exception as exc:
        session["error"] = str(exc)
        session["status"] = "NOT_ATTACHED"
        return session
    account = account_identity_snapshot(mt5)
    term = terminal_build_snapshot(mt5)
    info = mt5.terminal_info()
    session["broker"] = account.get("broker") or UNKNOWN
    session["server"] = account.get("server") or UNKNOWN
    session["environment"] = account.get("trade_mode_label") or UNKNOWN
    session["login_identity"] = account.get("login_identity") or UNKNOWN
    session["connected"] = bool(term.get("connected"))
    session["build"] = term.get("build") or UNKNOWN
    session["path"] = str(getattr(info, "path", None) or exe) if info is not None else exe
    session["account"] = account
    try:
        session["open_positions"] = int(mt5.positions_total() or 0)
        session["open_orders"] = int(mt5.orders_total() or 0)
    except Exception:
        session["open_positions"] = UNKNOWN
        session["open_orders"] = UNKNOWN
    session["positions_touched"] = False
    session["orders_touched"] = False
    session["catalog"] = catalog_existence_check(mt5)
    session["symbols"] = {
        CANONICAL_SYMBOL: _augment_symbol_fields(
            mt5, _enrich_symbol(mt5, CANONICAL_SYMBOL, session["catalog"])
        ),
        LOGICAL_SYMBOL: _augment_symbol_fields(
            mt5, _enrich_symbol(mt5, LOGICAL_SYMBOL, session["catalog"])
        ),
    }
    session["retrieval_timestamp_utc"] = _utc_now()
    return session


def _augment_symbol_fields(mt5: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Add requested economics fields without calling symbol_select."""
    if row.get("existence") != "YES":
        for report, _attr in EXTRA_SYMBOL_ATTRS:
            row.setdefault(report, UNKNOWN)
        return row
    info = mt5.symbol_info(row.get("symbol"))
    if info is None:
        return row
    for report, attr in EXTRA_SYMBOL_ATTRS:
        if row.get(report) in (None, UNKNOWN) or report not in row:
            val = getattr(info, attr, UNKNOWN)
            row[report] = val if val is not None else UNKNOWN
    return row


def _filter_immutability_issues(issues: list[str]) -> list[str]:
    allowed = tuple(PHASE38_RESEARCH_FILES)
    kept = []
    for item in issues:
        name = item.split(":", 1)[-1]
        if name in allowed:
            continue
        kept.append(item)
    return kept


def slice_last_calendar_days(df: pd.DataFrame, days: float) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    idx = pd.to_datetime(df.index, utc=True)
    end = idx.max()
    start = end - pd.Timedelta(days=float(days))
    mask = idx >= start
    return df.loc[mask].copy()


def _duration_days(df: pd.DataFrame) -> float:
    if df is None or df.empty:
        return 0.0
    idx = pd.to_datetime(df.index, utc=True)
    return float((idx.max() - idx.min()).total_seconds() / 86400.0)


def collect_history_readonly() -> dict[str, Any]:
    out: dict[str, Any] = {
        "deals": 0,
        "orders": 0,
        "gold_deals": 0,
        "commission_values": [],
        "swap_values": [],
        "requested_vs_filled_pairs": 0,
        "grade": "NOT_OBSERVED",
        "error": None,
    }
    try:
        import MetaTrader5 as mt5
    except ImportError:
        out["error"] = "MetaTrader5 package not installed"
        return out
    end = datetime.now(timezone.utc)
    start = HISTORY_LOOKBACK_START
    out["lookback_start"] = start.isoformat().replace("+00:00", "Z")
    out["lookback_end"] = end.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        deals = mt5.history_deals_get(start, end) or []
        orders = mt5.history_orders_get(start, end) or []
    except Exception as exc:
        out["error"] = str(exc)
        return out
    out["deals_total"] = int(len(deals))
    out["orders_total"] = int(len(orders))
    out["deals"] = min(int(len(deals)), MAX_HISTORY_ROWS)
    out["orders"] = min(int(len(orders)), MAX_HISTORY_ROWS)
    gold = 0
    commissions = []
    swaps = []
    for deal in list(deals)[:MAX_HISTORY_ROWS]:
        sym = str(getattr(deal, "symbol", "") or "")
        if "XAU" in sym.upper() or "GOLD" in sym.upper():
            gold += 1
            commissions.append(float(getattr(deal, "commission", 0) or 0))
            swaps.append(float(getattr(deal, "swap", 0) or 0))
    out["gold_deals"] = gold
    out["commission_values"] = commissions[:50]
    out["swap_values"] = swaps[:50]
    out["all_gold_commission_zero"] = bool(commissions) and all(v == 0 for v in commissions)
    out["all_gold_swap_zero"] = bool(swaps) and all(v == 0 for v in swaps)
    out["requested_vs_filled_pairs"] = 0
    out["price_open_is_not_requested"] = True
    out["mt5_deviation_is_not_realized_slippage"] = True
    out["grade"] = "DEAL_FILL_TAPE_ONLY" if deals else "NOT_OBSERVED"
    return out


def gap_item(**kwargs: Any) -> dict[str, Any]:
    keys = (
        "evidence_id",
        "requirement",
        "current_state",
        "required_state",
        "available_sources",
        "best_source",
        "acquisition_method",
        "safety_risk",
        "mt5_required",
        "mt5_must_be_launched",
        "estimated_achievable_coverage",
        "blocking_reason",
        "final_status",
    )
    return {k: kwargs.get(k) for k in keys}


def build_gap_matrix(root: Path, *, discovery: dict[str, Any], selected: dict[str, Any]) -> list[dict[str, Any]]:
    p35 = _safe_load_json(root / PHASE35_JSON) or {}
    comps = p35.get("cost_components") or {}
    installed = bool(discovery.get("installed"))
    running = bool(discovery.get("terminal64_running"))
    must_launch = installed and not running
    exe = ((selected.get("selected") or {}) or {}).get("terminal_exe")
    logical = [p for p in BLOCKED_LOGICAL_TAPES if (root / p).is_file()]
    return [
        gap_item(
            evidence_id="DATA_M5_LONG_HORIZON",
            requirement=">=60 days XAUUSD_i M5 (preferred 180)",
            current_state="~14.88 days frozen XAUUSD_i_5m.parquet",
            required_state=">=60 calendar days",
            available_sources=["MT5 copy_rates XAUUSD_i", *logical],
            best_source="MT5 XAUUSD_i copy_rates" if exe else "none",
            acquisition_method="launch identified terminal + chunked copy_rates_from_pos",
            safety_risk="LOW if read-only; launching GUI only",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="broker-history-dependent",
            blocking_reason=None if exe else "no project-relevant terminal",
            final_status="PENDING_ACQUISITION",
        ),
        gap_item(
            evidence_id="DATA_M15",
            requirement="supporting XAUUSD_i M15",
            current_state="NOT_OBSERVED canonical M15",
            required_state="optional supporting tape",
            available_sources=["MT5 M15", "data/ml/raw/candles/m15/XAUUSD_m15.parquet (logical XAUUSD, blocked)"],
            best_source="MT5 XAUUSD_i M15",
            acquisition_method="copy_rates M15 after M5",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="optional",
            blocking_reason=None,
            final_status="PENDING_ACQUISITION",
        ),
        gap_item(
            evidence_id="DATA_M1",
            requirement="supporting XAUUSD_i M1",
            current_state="NOT_OBSERVED",
            required_state="optional bounded tape",
            available_sources=["MT5 M1"],
            best_source="MT5 XAUUSD_i M1",
            acquisition_method="bounded copy_rates M1",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="resource-bounded",
            blocking_reason=None,
            final_status="PENDING_ACQUISITION",
        ),
        gap_item(
            evidence_id="DATA_TICKS",
            requirement="historical ticks where safe",
            current_state="no phase37 ticks",
            required_state="optional OBSERVED ticks",
            available_sources=["MT5 copy_ticks_range"],
            best_source="MT5 ticks",
            acquisition_method="bounded 7-day tick window",
            safety_risk="MEDIUM resource",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="partial",
            blocking_reason=None,
            final_status="PENDING_ACQUISITION",
        ),
        gap_item(
            evidence_id="BID_ASK",
            requirement="historical Bid/Ask OBSERVED",
            current_state="sidecar 27.26 OBSERVED ~15d; production PROXY",
            required_state="DATASET Bid/Ask for cost gate",
            available_sources=["logs/phase27_26_xauusd_i_m5_bidask.parquet", "MT5 ticks"],
            best_source="MT5 ticks if available else keep 27.26",
            acquisition_method="bounded ticks; never relabel PROXY as OBSERVED",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="partial",
            blocking_reason="production parquet remains PROXY unless ingested (not this phase)",
            final_status="PARTIAL",
        ),
        gap_item(
            evidence_id="SYMBOL_ECONOMICS",
            requirement="current XAUUSD_i contract fields",
            current_state=(comps.get("economics") or {}).get("and_status") or UNKNOWN,
            required_state="OBSERVED current spec; historical completeness separate",
            available_sources=["symbol_info attach-only"],
            best_source="attached symbol_info",
            acquisition_method="inspect_symbol_readonly",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="current snapshot only",
            blocking_reason=None,
            final_status="PENDING_ACQUISITION",
        ),
        gap_item(
            evidence_id="COMMISSION",
            requirement="account-applicable VERIFIED_SCHEDULE",
            current_state="UNKNOWN / OBSERVED_ZERO_NOT_PROVEN",
            required_state="VERIFIED_SCHEDULE",
            available_sources=["history_deals_get", "logs/phase27_28_commission_evidence.json"],
            best_source="deals + prior forensic",
            acquisition_method="read-only deal commissions; zeros ≠ verified",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="still not VERIFIED_SCHEDULE if zeros/unknown product",
            blocking_reason="account product type UNKNOWN",
            final_status="BLOCKED",
        ),
        gap_item(
            evidence_id="SWAP",
            requirement="historical swap series or BROKER_RATE_ONLY current",
            current_state="CURRENT_BROKER_RATE_ONLY / historical UNKNOWN",
            required_state="OBSERVED_HISTORICAL or documented BROKER_RATE_ONLY",
            available_sources=["symbol_info swap_*", "deal.swap"],
            best_source="symbol_info + deals",
            acquisition_method="current rates OBSERVED; short-hold zeros not historical zero",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="BROKER_RATE_ONLY",
            blocking_reason="no historical series",
            final_status="UNKNOWN",
        ),
        gap_item(
            evidence_id="SLIPPAGE",
            requirement="genuine requested vs executed pairs",
            current_state="0 pairs; MODELED",
            required_state="OBSERVED pairs or remain MODELED",
            available_sources=["order/deal history", "logs/phase27_30_slippage_evidence.json"],
            best_source="history_orders_get vs deals",
            acquisition_method="do not treat price_open/deviation as requested",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="likely still MODELED",
            blocking_reason="requested price not identifiable",
            final_status="MODELED",
        ),
        gap_item(
            evidence_id="ORDER_HISTORY",
            requirement="order lifecycle tape",
            current_state="0 orders in prior tape",
            required_state="linkable orders",
            available_sources=["history_orders_get"],
            best_source="MT5 history",
            acquisition_method="read-only history_orders_get",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="unknown",
            blocking_reason=None,
            final_status="PENDING_ACQUISITION",
        ),
        gap_item(
            evidence_id="DEAL_HISTORY",
            requirement="deal fill tape",
            current_state="prior DEAL_FILL_TAPE_ONLY",
            required_state="gold deals if any",
            available_sources=["history_deals_get"],
            best_source="MT5 history",
            acquisition_method="read-only history_deals_get",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="account-dependent",
            blocking_reason=None,
            final_status="PENDING_ACQUISITION",
        ),
        gap_item(
            evidence_id="REQUESTED_VS_FILLED",
            requirement="genuine request/fill pairs",
            current_state="0",
            required_state="n>0 or remain unidentified",
            available_sources=["orders+deals"],
            best_source="order price vs deal price if requested stored",
            acquisition_method="do not fabricate pairs",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="likely 0",
            blocking_reason="requested not stored",
            final_status="NOT_IDENTIFIABLE",
        ),
        gap_item(
            evidence_id="EXECUTION_BEHAVIOR",
            requirement="partials/rejects/requotes/latency",
            current_state="UNKNOWN / DEAL_FILL_TAPE_ONLY",
            required_state="lifecycle tape",
            available_sources=["history_orders_get states"],
            best_source="MT5 orders",
            acquisition_method="read-only; no order modification",
            safety_risk="LOW",
            mt5_required=True,
            mt5_must_be_launched=must_launch,
            estimated_achievable_coverage="likely DEAL_FILL_TAPE_ONLY",
            blocking_reason=None,
            final_status="UNKNOWN",
        ),
        gap_item(
            evidence_id="SYMBOL_BINDING",
            requirement="XAUUSD_i canonical; XAUUSD only with explicit map",
            current_state="EV-EQ-01 NOT_PROVEN; empty map; 30 logical XAUUSD blocked",
            required_state="no silent map; EV-EQ-01 remains NOT_PROVEN unless both observed",
            available_sources=logical,
            best_source="do not merge logical tapes",
            acquisition_method="keep map empty; record XAUUSD presence on this terminal only",
            safety_risk="HIGH if merged (forbidden)",
            mt5_required=False,
            mt5_must_be_launched=False,
            estimated_achievable_coverage="policy preserved",
            blocking_reason="EV-EQ-01 NOT_PROVEN",
            final_status="BLOCKED",
        ),
    ]


def ny_only_scan(enriched: Any, *, symbol: str) -> list[dict[str, Any]]:
    """Closed-bar Phase 28 scan with NY hour check before window copy.

    Phase 28 already skipped generate_signals outside NY; this only avoids
    O(n^2) frame copies on those skipped bars. Sequential PA state is still
    only updated during NY hours, matching the official scanner.
    """
    cfg = get_price_action_config(symbol, "M5")
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    legacy = apply_pa_to_legacy(load_legacy_config(), symbol, "M5")
    clear_pa_dedup_cache()
    pa = PriceActionStrategy(legacy)
    idx = enriched.index
    out: list[dict[str, Any]] = []
    for cursor in range(WARMUP, len(enriched)):
        ts = idx[cursor]
        hour = int(getattr(ts, "hour", -1))
        if not (ny_s <= hour < ny_e):
            continue
        window = _append_forming_bar_m5(enriched.iloc[: cursor + 1])
        closed = exclude_forming_bar(window, min_rows=30)
        if closed is None or closed.empty:
            continue
        i = len(closed) - 1
        closed_ts = closed.index[i]
        closed_hour = int(getattr(closed_ts, "hour", -1))
        if not (ny_s <= closed_hour < ny_e):
            continue
        sigs = pa.generate_signals(closed, symbol=symbol, timeframe="M5")
        if not sigs:
            continue
        sig = sigs[0]
        direction = getattr(getattr(sig, "signal_type", None), "name", None) or str(
            getattr(sig, "signal_type", UNKNOWN)
        )
        meta = getattr(sig, "metadata", None) or {}
        entry = float(getattr(sig, "price", closed.iloc[i]["close"]))
        sl = float(meta.get("stop_loss") or 0.0)
        tp = float(meta.get("take_profit") or 0.0)
        full_idx = int(enriched.index.get_indexer([closed.index[i]], method="nearest")[0])
        result = theoretical_outcome(enriched, full_idx, direction, entry, sl, tp)
        out.append(
            {
                "timestamp": str(closed.index[i]),
                "cursor": int(cursor),
                "closed_bar_index": int(full_idx),
                "direction": direction,
                "side": "BUY" if "BUY" in str(direction).upper() else "SELL" if "SELL" in str(direction).upper() else direction,
                "entry_price": entry,
                "stop_loss": sl,
                "take_profit": tp,
                "planned_rr": meta.get("risk_reward_ratio"),
                "confidence": float(getattr(sig, "confidence", 0) or 0),
                "quality_score": meta.get("quality_score"),
                "setup": meta.get("setup") or meta.get("pattern"),
                "symbol": getattr(sig, "symbol", symbol),
                "asian_high": meta.get("asian_high"),
                "asian_low": meta.get("asian_low"),
                **result,
                "entry_timing": (
                    "Signal on last CLOSED M5 bar only. Forming bar is appended then excluded. "
                    "Entry price = strategy setup.entry from that closed bar. "
                    "Theoretical exits start at the next bar (i+1). Same-bar SL before TP."
                ),
            }
        )
    return out


def _attach_official_asian_range(setups: list[dict[str, Any]], enriched: Any, *, symbol: str) -> list[dict[str, Any]]:
    """Mechanical Asian range from the same production function the live evaluator uses.

    PriceActionStrategy Signal.metadata does not copy asian_high/low. Reconstructing
    those two numbers from closed bars is not a parameter change and is not silent
    symbol mapping.
    """
    cfg = get_price_action_config(symbol, "M5")
    start = int(cfg.get("ASIAN_START_HOUR", 0))
    end = m5_asian_end_hour(cfg)
    out = []
    for s in setups:
        row = dict(s)
        if row.get("asian_high") is not None and row.get("asian_low") is not None:
            out.append(row)
            continue
        i = int(row.get("closed_bar_index") if row.get("closed_bar_index") is not None else row["cursor"])
        bounds = asian_range(enriched, i, start_hour=start, end_hour=end, min_bars=4)
        if bounds:
            row["asian_high"] = float(bounds[0])
            row["asian_low"] = float(bounds[1])
        out.append(row)
    return out


def _compact_setup(s: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "timestamp",
        "cursor",
        "closed_bar_index",
        "direction",
        "side",
        "entry_price",
        "stop_loss",
        "take_profit",
        "planned_rr",
        "confidence",
        "quality_score",
        "setup",
        "asian_high",
        "asian_low",
        "outcome",
        "r_multiple",
        "exit_time",
        "exit_index",
    )
    return {k: s.get(k) for k in keys}


def evaluate_unchanged_strategy(m5_frame: pd.DataFrame, *, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """RAW closed-bar scan + separate RiskGate executable book. No optimization."""
    full_days = _duration_days(m5_frame)
    scan_frame = slice_last_calendar_days(m5_frame, SCAN_DAYS)
    scan_days = _duration_days(scan_frame)
    event_block: dict[str, Any] = {
        "ran": False,
        "event_count": None,
        "signal_count": None,
        "classification": "INSUFFICIENT",
        "scan_window_days": scan_days,
        "full_tape_days": full_days,
        "note": "not scanned",
    }
    strategy_block: dict[str, Any] = {
        "ran": False,
        "reason": "scan not executed",
        "raw": None,
        "executable": None,
        "optimized": False,
        "parameters_changed": False,
    }
    if scan_frame is None or scan_frame.empty or scan_days < MIN_DAYS:
        event_block["note"] = f"scan window {scan_days:.2f}d below {MIN_DAYS}d floor"
        return event_block, strategy_block

    enriched = _enrich_frame(scan_frame)
    setups_path = root / PHASE38_SETUPS
    loaded_setups = None
    if setups_path.is_file():
        try:
            blob = json.loads(setups_path.read_text(encoding="utf-8"))
            if (
                str(blob.get("scan_start")) == str(scan_frame.index.min())
                and str(blob.get("scan_end")) == str(scan_frame.index.max())
                and int(blob.get("scan_rows") or 0) == int(len(scan_frame))
                and isinstance(blob.get("setups"), list)
                and blob.get("setups")
            ):
                loaded_setups = list(blob["setups"])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            loaded_setups = None
    if loaded_setups is None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            setups = ny_only_scan(enriched, symbol=PRIMARY_SYMBOL)
        setups_path.parent.mkdir(parents=True, exist_ok=True)
        setups_path.write_text(
            json.dumps(
                {
                    "scan_start": str(scan_frame.index.min()),
                    "scan_end": str(scan_frame.index.max()),
                    "scan_rows": int(len(scan_frame)),
                    "setups": [_compact_setup(s) for s in setups],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    else:
        setups = loaded_setups
    setups = _attach_official_asian_range(setups, enriched, symbol=PRIMARY_SYMBOL)
    if loaded_setups is not None:
        setups_path.write_text(
            json.dumps(
                {
                    "scan_start": str(scan_frame.index.min()),
                    "scan_end": str(scan_frame.index.max()),
                    "scan_rows": int(len(scan_frame)),
                    "setups": [_compact_setup(s) for s in setups],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    rows = []
    skipped_missing_range = 0
    for i, s in enumerate(setups):
        row = dict(s)
        row["signal_id"] = row.get("signal_id") or f"P38-{i+1:04d}"
        row["theoretical_R"] = row.get("theoretical_R", row.get("r_multiple"))
        if row.get("asian_high") is None or row.get("asian_low") is None:
            skipped_missing_range += 1
            continue
        rows.append(row)
    labeled = assign_mechanical_events(rows) if rows else []
    metrics = event_metrics(labeled) if labeled else {"event_count": 0, "signal_count": 0}
    n_events = int(metrics.get("event_count") or 0)
    rs = [float(s["r_multiple"]) for s in setups if s.get("r_multiple") is not None]
    wins = sum(1 for s in setups if s.get("outcome") == "win")
    losses = sum(1 for s in setups if s.get("outcome") == "loss")
    event_block = {
        "ran": True,
        "event_count": n_events,
        "signal_count": int(metrics.get("signal_count") or len(rows)),
        "classification": "SUFFICIENT" if n_events >= MIN_EVENTS else "INSUFFICIENT",
        "raw_setups": len(setups),
        "setups_missing_asian_range": skipped_missing_range,
        "scan_window_days": scan_days,
        "full_tape_days": full_days,
        "scan_start": str(scan_frame.index.min()),
        "scan_end": str(scan_frame.index.max()),
        "scan_rows": int(len(scan_frame)),
        "parameters_changed": False,
        "event_definition": "(UTC date, asian_high, asian_low, side)",
        "independence_manufactured": False,
        "signals_per_event_mean": (metrics.get("signals_per_event") or {}).get("mean"),
        "singleton_events": metrics.get("singleton_events"),
        "clustered_events": metrics.get("clustered_events"),
        "asian_range_source": "tradingbot.domain.gold_strategies.m5_london_sweep.asian_range",
        "note": (
            f"Unchanged gold_ny_sweep on last {SCAN_DAYS}d of phase38 XAUUSD_i M5. "
            "Not a production verdict. Events are mechanical, not manufactured."
        ),
    }
    raw_book = {
        "n": len(setups),
        "wins": wins,
        "losses": losses,
        "expectancy_R": (sum(rs) / len(rs)) if rs else None,
        "resolved": len(rs),
        "unresolved": len(setups) - len(rs),
        "cost_adjusted": False,
        "book": "RAW_SIGNAL",
    }
    executable: dict[str, Any] = {
        "book": "EXECUTABLE",
        "ran": False,
        "reason": "not yet",
    }
    prev = _safe_load_json(root / PHASE38_JSON) or {}
    prev_exe = ((prev.get("strategy_evaluation") or {}).get("executable") or {})
    if (
        prev_exe.get("ran")
        and int(prev_exe.get("candidates") or -1) == len(setups)
        and prev_exe.get("mixed_with_raw") is False
    ):
        executable = dict(prev_exe)
        executable["reused_prior_phase38_executable"] = True
    else:
        try:
            research = build_research_configuration()
            h4 = None
            h4_path = root / H4_CONTEXT_PARQUET
            if h4_path.is_file():
                h4 = load_parquet_utc(h4_path)
            engine = _build_research_engine(enriched, research, h4=h4)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                executable = asyncio.run(evaluate_executable_edge(engine, setups, research))
            executable = {
                "book": "EXECUTABLE",
                "ran": True,
                "candidates": executable.get("candidates"),
                "allowed": executable.get("allowed"),
                "rejected": executable.get("rejected"),
                "rejection_reasons": executable.get("rejection_reasons"),
                "executed_simulated_trades": executable.get("executed_simulated_trades"),
                "broker_fill_note": executable.get("broker_fill_note"),
                "mixed_with_raw": False,
            }
        except Exception as exc:
            executable = {
                "book": "EXECUTABLE",
                "ran": False,
                "reason": f"RiskGate replay failed: {exc}",
                "mixed_with_raw": False,
            }
    strategy_block = {
        "ran": True,
        "raw": raw_book,
        "executable": executable,
        "optimized": False,
        "parameters_changed": False,
        "lookahead_safeguards": True,
        "same_bar_sl_before_tp": True,
        "closed_bar_only": True,
        "note": (
            "Unchanged gold_ny_sweep closed-bar scan. RAW is theoretical SL/TP. "
            "EXECUTABLE is RiskGate only and is not mixed into RAW. "
            "Not a production profitability verdict."
        ),
    }
    return event_block, strategy_block


def finalize_gap_matrix(
    gaps: list[dict[str, Any]],
    *,
    m5_days: float,
    m15_ok: bool,
    m1_status: str,
    ticks_status: str,
    bidask_status: str,
    attached: bool,
    xau_i_present: bool,
    history: dict[str, Any],
) -> list[dict[str, Any]]:
    overlay = {
        "DATA_M5_LONG_HORIZON": (
            "MET_PREFERRED" if m5_days >= TARGET_DAYS else "MET_MIN" if m5_days >= MIN_DAYS else "INSUFFICIENT"
        ),
        "DATA_M15": "OBSERVED" if m15_ok else "NOT_OBSERVED",
        "DATA_M1": m1_status,
        "DATA_TICKS": ticks_status,
        "BID_ASK": bidask_status,
        "SYMBOL_ECONOMICS": "CURRENT_SNAPSHOT" if attached and xau_i_present else "UNKNOWN",
        "COMMISSION": "UNKNOWN",
        "SWAP": "BROKER_RATE_ONLY" if attached and xau_i_present else "UNKNOWN",
        "SLIPPAGE": "MODELED",
        "ORDER_HISTORY": (
            "DEAL_FILL_TAPE_ONLY"
            if int(history.get("orders_total") or history.get("orders") or 0) > 0
            else "NOT_OBSERVED"
        ),
        "DEAL_HISTORY": (
            "DEAL_FILL_TAPE_ONLY"
            if int(history.get("deals_total") or history.get("deals") or 0) > 0
            else "NOT_OBSERVED"
        ),
        "REQUESTED_VS_FILLED": "NOT_IDENTIFIABLE",
        "EXECUTION_BEHAVIOR": history.get("grade") or "NOT_OBSERVED",
        "SYMBOL_BINDING": "BLOCKED",
    }
    out = []
    for row in gaps:
        item = dict(row)
        evid = item.get("evidence_id")
        if evid in overlay:
            item["final_status"] = overlay[evid]
            if evid == "DATA_M5_LONG_HORIZON":
                item["current_state"] = f"{m5_days:.4f} days phase38 XAUUSD_i M5 (frozen tape still 14.88d)"
                item["blocking_reason"] = None if m5_days >= MIN_DAYS else item.get("blocking_reason")
        out.append(item)
    return out


def evaluate_cost_gate(prior: dict[str, Any], *, attached: bool, m5_days: float, ticks_observed: bool, history: dict[str, Any], xau_i_present: bool) -> dict[str, Any]:
    comps = dict(prior.get("cost_components") or {})
    overlay = {
        "symbol_binding": {"status": "BLOCKED", "note": "EV-EQ-01 NOT_PROVEN; empty map; not weakened"},
        "economics": {
            "status": "PARTIAL" if attached and xau_i_present else (comps.get("economics") or {}).get("and_status") or "UNKNOWN",
            "note": "current symbol_info snapshot is not a complete historical economics series",
        },
        "dataset_provenance": {"status": "PARTIAL", "note": "new phase38 tape sidecar PROXY ohlc_only if written"},
        "spread": {
            "status": "BLOCKED",
            "note": "production parquet remains PROXY; new ticks if any are separate OBSERVED",
        },
        "commission": {
            "status": "BLOCKED",
            "note": "deal zeros are OBSERVED_ZERO_NOT_PROVEN; VERIFIED_SCHEDULE not met",
        },
        "swap": {
            "status": "UNKNOWN",
            "note": "current rates may be OBSERVED; historical series still UNKNOWN",
        },
        "slippage": {
            "status": "UNKNOWN",
            "note": "MODELED; requested-vs-fill pairs still 0 unless proven",
        },
        "execution_model": {
            "status": "UNKNOWN",
            "note": history.get("grade") or "UNKNOWN",
        },
    }
    if ticks_observed:
        overlay["spread"]["sidecar_grade"] = "OBSERVED"
    if m5_days >= MIN_DAYS:
        overlay["dataset_provenance"]["note"] += f"; phase38 M5 {m5_days:.2f}d is new research tape not production"
    ready = cost_ready_for_validation({k: {"status": v["status"]} for k, v in overlay.items()})
    return {
        "components": overlay,
        "complete_count": sum(1 for v in overlay.values() if component_is_complete(v["status"])),
        "required_count": len(GATE_COMPONENTS),
        "cost_ready_for_validation": ready,
        "gate_weakened": False,
        "classification": "COMPLETE" if ready else "INCOMPLETE",
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    (root / PHASE38_MD).parent.mkdir(parents=True, exist_ok=True)
    cmp_rows = "\n".join(
        f"| {r['requirement']} | {r['previous']} | {r['phase38']} | {r['improvement']} | {r['status']} |"
        for r in payload.get("comparison") or []
    )
    m5 = payload.get("m5") or {}
    cov = m5.get("coverage") or {}
    gaps_cov = (cov.get("gap_classification") or {}) if isinstance(cov, dict) else {}
    ev = payload.get("event_sufficiency") or {}
    st = payload.get("strategy_evaluation") or {}
    raw = st.get("raw") or {}
    exe = st.get("executable") or {}
    xi = (payload.get("symbols") or {}).get("XAUUSD_i") or {}
    xau = (payload.get("symbols") or {}).get("XAUUSD") or {}
    attach = (payload.get("mt5_discovery") or {}).get("attach") or {}
    launch = (payload.get("mt5_discovery") or {}).get("launch") or {}
    cost = payload.get("cost_completeness") or {}
    (root / PHASE38_MD).write_text(
        f"""# Phase 38 — Intelligent Evidence Acquisition

**STATUS:** `{payload.get("status")}`
**Class:** RESEARCH / DATA ACQUISITION ONLY
**MT5 launched by this phase:** `{launch.get("launched_by_phase")}`
**Real account interaction:** `{payload.get("real_account_interaction")}`
**Frozen dataset changed:** `{False if payload.get("fingerprints", {}).get("phase28_m5_unchanged") else True}`
**Production changes:** `NONE`
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`
**BLOCKER_REMAINING:** `{payload.get("BLOCKER_REMAINING")}`

STOP AFTER PHASE 38. DO NOT START PHASE 39.
DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.

This phase does **not** produce a strategy profitability verdict. Phase 36 `INSUFFICIENT_EVIDENCE` is reduced only where new evidence actually landed.

---

## 1. What was discovered

{payload.get("discovery_summary")}

- Selected terminal: LiteFinance-MT5-Live at `C:\\Program Files\\MetaTrader 5\\terminal64.exe`
- FIBO Group data dir observed and **not launched** (other broker)
- Logical `XAUUSD` tapes exist on disk and remain **BLOCKED** (`MISSING_EXPLICIT_MAP`, EV-EQ-01 `NOT_PROVEN`)

## 2. What evidence was acquired

{payload.get("acquired_summary")}

M5 research tape: `{m5.get("path")}`  
Rows: `{m5.get("rows")}` · Days: `{m5.get("days")}` · Start: `{m5.get("start")}` · End: `{m5.get("end")}`  
Cap hit (250k M5 bars): `{m5.get("cap_hit")}` — actual broker history may be longer  
Duplicates: `{cov.get("duplicate_timestamps")}` · Impossible OHLC: `{cov.get("impossible_ohlc")}` · Zero volume: `{cov.get("zero_volume")}`  
Gaps: weekend `{gaps_cov.get("EXPECTED_WEEKEND_GAP")}` · rollover `{gaps_cov.get("BROKER_ROLLOVER_GAP")}` · unknown `{gaps_cov.get("UNKNOWN_GAP")}`  
SHA-256 file: `{payload.get("fingerprints", {}).get("phase38_m5_file")}`  
SHA-256 content: `{payload.get("fingerprints", {}).get("phase38_m5_content")}`

Frozen Phase 28 `data/XAUUSD_i_5m.parquet` fingerprint unchanged: `{payload.get("fingerprints", {}).get("phase28_m5_unchanged")}`

## 3. What remains missing

{payload.get("missing_summary")}

## 4. Terminal / account (read-only)

Status: `{attach.get("status")}`  
Launched by Phase 38: `{launch.get("launched_by_phase")}` (already running: `{launch.get("already_running")}`)  
Broker / server / env: `{attach.get("broker")}` / `{attach.get("server")}` / `{attach.get("environment")}`  
Open positions / orders observed, not touched: `{attach.get("open_positions")}` / `{attach.get("open_orders")}`

## 5. Symbols

`XAUUSD_i` existence: `{xi.get("existence")}`  
digits `{xi.get("digits")}` · point `{xi.get("point")}` · contract `{xi.get("contract_size")}` · tick `{xi.get("tick_size")}`  
swap_long `{xi.get("swap_long")}` · swap_short `{xi.get("swap_short")}` · rollover3days `{xi.get("swap_rollover3days")}`  
bid `{xi.get("bid")}` · ask `{xi.get("ask")}` · quote `{xi.get("quote_utc")}` · description `{xi.get("description")}`

`XAUUSD` existence: `{xau.get("existence")}`

Absence is **terminal-scoped**. Do not conclude XAUUSD does not exist broker-wide. EV-EQ-01 remains **NOT_PROVEN**. `dataset_symbol_map` is empty. No silent mapping.

## 6. Bid/Ask / spread

Phase 38 ticks: **NOT_OBSERVED** (`SKIPPED_RESOURCE_BOUND` — gold `copy_ticks_range` hung in Phase 37/38 reconnaissance).  
Live bid/ask on attach is a **current quote**, not a historical Bid/Ask tape.  
Prior sidecar `logs/phase27_26_xauusd_i_m5_bidask.parquet` remains OBSERVED for ~15d only.  
Production parquet remains **PROXY**. OHLC-derived spread is **PROXY**, not observed Bid/Ask.

## 7. Commission / swap / slippage / execution

- Commission: `{payload.get("commission")}`
- Swap: `{payload.get("swap")}` — current broker rates only; historical series **UNKNOWN**. Short-hold zeros would not prove historical swap is zero.
- Slippage: `{payload.get("slippage")}` — `deal.price` / `price_open` / deviation are **not** requested price.
- Execution: `{payload.get("execution")}`

## 8. Cost completeness AND-gate (not weakened)

Ready: `{cost.get("cost_ready_for_validation")}`  
Classification: `{cost.get("classification")}` · complete `{cost.get("complete_count")}/{cost.get("required_count")}`  
Gate weakened: `{cost.get("gate_weakened")}`

Components: symbol_binding `{((cost.get("components") or {}).get("symbol_binding") or {}).get("status")}` · economics `{((cost.get("components") or {}).get("economics") or {}).get("status")}` · provenance `{((cost.get("components") or {}).get("dataset_provenance") or {}).get("status")}` · spread `{((cost.get("components") or {}).get("spread") or {}).get("status")}` · commission `{((cost.get("components") or {}).get("commission") or {}).get("status")}` · swap `{((cost.get("components") or {}).get("swap") or {}).get("status")}` · slippage `{((cost.get("components") or {}).get("slippage") or {}).get("status")}` · execution `{((cost.get("components") or {}).get("execution_model") or {}).get("status")}`

## 9. Events / unchanged-strategy research scan

Scan ran: `{ev.get("ran")}` · window `{ev.get("scan_window_days")}` days of the phase38 tape (full tape `{ev.get("full_tape_days")}` days)  
RAW setups: `{ev.get("raw_setups")}` · mechanical events: `{ev.get("event_count")}` · classification: `{ev.get("classification")}`  
Event definition (unchanged): `(UTC date, asian_high, asian_low, side)`  
Independence manufactured: `{ev.get("independence_manufactured")}`

RAW book: n=`{raw.get("n")}` wins=`{raw.get("wins")}` losses=`{raw.get("losses")}` expectancy_R=`{raw.get("expectancy_R")}` (theoretical SL/TP, not cost-adjusted)

EXECUTABLE book: ran=`{exe.get("ran")}` allowed=`{exe.get("allowed")}` rejected=`{exe.get("rejected")}` fills=`{exe.get("executed_simulated_trades")}`  
RAW and EXECUTABLE are **not mixed**. Zero fills is not a no-edge proof (commission UNKNOWN fail-closed).

This is **not** a production strategy verdict.

## 10. Comparison vs Phase 36 blockers

| Requirement | Previous | Phase38 | Improvement | Status |
|---|---|---|---|---|
{cmp_rows}

**BLOCKER_REMAINING:** `{payload.get("BLOCKER_REMAINING")}`

## 11. Recommended next phase

{payload.get("recommended_next_phase")}

## Safety

No orders, no `.env`, no frozen parquet rewrite, no bot/daemon, no optimization, no ML activation.
Phase 39 was **not** started.
""",
        encoding="utf-8",
    )


def _patch_truth_docs(root: Path, *, status: str) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Intelligent evidence acquisition (Phase 38)"
        block = (
            "\n\n## Intelligent evidence acquisition (Phase 38)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            f"| Phase 38 status | **{status}** |\n"
            "| Frozen Phase 28/30 M5 overwritten | **NO** |\n"
            "| Silent XAUUSD map | **NO** |\n"
            "| .env read | **NO** |\n"
            "| Orders sent / bot started | **NO** |\n"
            "| Phase 39 started | **NO** |\n"
            "| Canonical XAUUSD_i M5 research tape (phase38) | **OBSERVED** — see PHASE38 artifact |\n"
            "| EV-EQ-01 | **NOT_PROVEN** |\n"
            "| Cost completeness | **INCOMPLETE** (gate not weakened) |\n"
            "| Strategy profitability verdict | **NOT ISSUED** |\n"
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
            f"| Phase 38 intelligent evidence | `run_phase38_collection()` | n/a | RESEARCH; may launch identified MT5; no bot/orders/.env | **{status}**; Phase 39 not started |"
        )
        text = re.sub(r"\| Phase 38 intelligent evidence \|.*\n", row + "\n", text)
        if "Phase 38 intelligent evidence" not in text:
            needle = "| Phase 37 long-horizon tape |"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + row + "\n" + text[end + 1 :]
        cfg.write_text(text, encoding="utf-8")
    sot = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    if sot.is_file():
        text = sot.read_text(encoding="utf-8")
        para = (
            "Phase 38 (`docs_v2/02_research/PHASE38_INTELLIGENT_EVIDENCE_ACQUISITION.md`) is intelligent "
            "evidence acquisition. It may launch an identified MT5 terminal. It does not start the bot, "
            "read `.env`, overwrite the frozen M5 snapshot, or authorize live trading.\n"
        )
        if "PHASE38_INTELLIGENT_EVIDENCE_ACQUISITION.md" not in text:
            marker = "Phase 37 (`docs_v2/02_research/PHASE37_LONG_HORIZON_TAPE.md`)"
            idx = text.find(marker)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + "\n" + para + text[end + 1 :]
                sot.write_text(text, encoding="utf-8")
    boundary = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    if boundary.is_file():
        text = boundary.read_text(encoding="utf-8")
        line = (
            "`tradingbot/backtest/phase38_intelligent_evidence_acquisition.py` — **RESEARCH_ONLY** "
            "intelligent evidence acquisition; may launch identified MT5; no bot/orders/.env; does not overwrite Phase 28 M5.  \n"
        )
        if "phase38_intelligent_evidence_acquisition.py" not in text:
            needle = "`tradingbot/backtest/phase37_long_horizon_tape.py`"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + line + text[end + 1 :]
                boundary.write_text(text, encoding="utf-8")


def run_phase38_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    frozen_fp = file_fingerprint(root / CANONICAL_PARQUET)
    if frozen_fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Frozen Phase 28/30 M5 fingerprint changed — Phase 38 refuses to proceed")
    frozen_df = load_parquet_utc(root / CANONICAL_PARQUET)
    frozen_content = content_fingerprint(frozen_df)
    prior35 = _safe_load_json(root / PHASE35_JSON) or {}

    discovery = discover_mt5_installations()
    selection = select_relevant_terminal(discovery)
    gaps = build_gap_matrix(root, discovery=discovery, selected=selection)
    launch = {"launched_by_phase": False, "ok": False, "already_running": terminal64_running()}
    attach: dict[str, Any] = {"ok": False, "status": "BLOCKED", "env_accessed": False}
    selected_exe = ((selection.get("selected") or {}) or {}).get("terminal_exe")

    if not discovery.get("installed") and not selected_exe:
        attach["status"] = "MT5_NOT_INSTALLED"
        attach["error"] = "no terminal64.exe found"
    elif not selected_exe:
        attach["status"] = "NO_RELEVANT_TERMINAL"
        attach["error"] = selection.get("reason")
    else:
        launch = launch_terminal(selected_exe)
        if launch.get("ok"):
            if not launch.get("already_running"):
                time.sleep(8)
            attach = attach_with_path(selected_exe)
        else:
            attach["status"] = "BLOCKED"
            attach["error"] = launch.get("error") or "launch failed"

    attached = bool(attach.get("ok"))
    symbols = attach.get("symbols") or {
        CANONICAL_SYMBOL: {"existence": UNKNOWN},
        LOGICAL_SYMBOL: {"existence": UNKNOWN},
    }
    xau_i = symbols.get(CANONICAL_SYMBOL) or {}
    xau = symbols.get(LOGICAL_SYMBOL) or {}
    if xau.get("existence") in {None, UNKNOWN, "NO"} and not attached:
        xau = {**xau, "existence": "NOT_OBSERVED_ON_THIS_TERMINAL", "broker_wide_absence_concluded": False}
    elif xau.get("existence") in {"NO", "ABSENT_ON_OBSERVED_TERMINAL"}:
        xau = {**xau, "existence": "NOT_OBSERVED_ON_THIS_TERMINAL", "broker_wide_absence_concluded": False}

    wrote: dict[str, Any] = {}
    m5_audit = None
    windows = strategy_window_coverage(pd.DataFrame())
    existing_m5 = root / PHASE38_M5
    reuse_m5 = existing_m5.is_file()
    collect_m5: dict[str, Any]
    m5_frame = None
    if reuse_m5:
        m5_frame = load_parquet_utc(existing_m5)
        collect_m5 = {
            "ok": True,
            "status": "OBSERVED",
            "rows": int(len(m5_frame)),
            "start": str(m5_frame.index.min()) if len(m5_frame) else None,
            "end": str(m5_frame.index.max()) if len(m5_frame) else None,
            "duration_days": _duration_days(m5_frame),
            "partial": int(len(m5_frame)) >= 250_000,
            "error": None,
            "reused_existing_phase38_tape": True,
            "cap_hit": int(len(m5_frame)) >= 250_000,
        }
        m5_audit = audit_dataset(m5_frame, timeframe="M5", path=PHASE38_M5)
        windows = strategy_window_coverage(m5_frame, step_minutes=5)
        wrote["m5"] = {
            "path": PHASE38_M5,
            "written": False,
            "reused": True,
            "rows": int(len(m5_frame)),
            "file_fingerprint": file_fingerprint(existing_m5),
            "content_fingerprint": content_fingerprint(m5_frame),
        }
    else:
        collect_m5 = collect_ohlc_chunked(timeframe="M5", attached=attached)
        m5_frame = collect_m5.pop("frame", None)
        if collect_m5.get("ok") and m5_frame is not None and len(m5_frame) > 0:
            wrote["m5"] = write_research_parquet(root, m5_frame, PHASE38_M5)
            m5_audit = audit_dataset(m5_frame, timeframe="M5", path=PHASE38_M5)
            windows = strategy_window_coverage(m5_frame, step_minutes=5)
            collect_m5["cap_hit"] = int(collect_m5.get("rows") or 0) >= 250_000
            collect_m5["reused_existing_phase38_tape"] = False

    collect_m15 = {"status": "NOT_ATTEMPTED", "ok": False, "rows": 0}
    collect_m1 = {"status": "SKIPPED_RESOURCE_BOUND", "ok": False, "rows": 0, "error": "M1 deferred so M5 completion is not blocked"}
    collect_ticks = {"status": "SKIPPED_RESOURCE_BOUND", "ok": False, "rows": 0, "error": "ticks deferred; copy_ticks_range can hang/exhaust memory on gold"}
    bidask_stats: dict[str, Any] = {"available": False, "status": "NOT_OBSERVED", "grade": None}
    existing_m15 = root / PHASE38_M15
    if existing_m15.is_file():
        m15_frame = load_parquet_utc(existing_m15)
        collect_m15 = {
            "status": "OBSERVED",
            "ok": True,
            "rows": int(len(m15_frame)),
            "duration_days": _duration_days(m15_frame),
            "error": None,
            "reused_existing_phase38_tape": True,
        }
        wrote["m15"] = {
            "path": PHASE38_M15,
            "written": False,
            "reused": True,
            "rows": int(len(m15_frame)),
            "file_fingerprint": file_fingerprint(existing_m15),
            "content_fingerprint": content_fingerprint(m15_frame),
        }
    elif attached and collect_m5.get("ok"):
        collect_m15 = collect_ohlc_chunked(timeframe="M15", attached=True)
        m15_frame = collect_m15.pop("frame", None)
        if collect_m15.get("ok") and m15_frame is not None and len(m15_frame) > 0:
            wrote["m15"] = write_research_parquet(root, m15_frame, PHASE38_M15)

    history = collect_history_readonly() if attached else {"grade": "NOT_OBSERVED", "requested_vs_filled_pairs": 0}
    days = float(collect_m5.get("duration_days") or 0)

    event_block: dict[str, Any] = {
        "ran": False,
        "event_count": 6,
        "signal_count": 24,
        "classification": "INSUFFICIENT",
        "note": "Phase 36 baseline 6 events / 24 signals on 14.88d frozen tape. Not re-run unless new tape >=60d.",
    }
    strategy_block: dict[str, Any] = {
        "ran": False,
        "reason": "tape below 60-day floor or not collected; Phase 36 INSUFFICIENT_EVIDENCE not replaced",
        "optimized": False,
        "parameters_changed": False,
    }
    if days >= MIN_DAYS and m5_frame is not None and len(m5_frame) > 0:
        event_block, strategy_block = evaluate_unchanged_strategy(m5_frame, root=root)

    xau_i_present = xau_i.get("existence") == "YES"
    gaps = finalize_gap_matrix(
        gaps,
        m5_days=days,
        m15_ok=bool(collect_m15.get("ok")),
        m1_status=str(collect_m1.get("status")),
        ticks_status=str(collect_ticks.get("status")),
        bidask_status=str(bidask_stats.get("status")),
        attached=attached,
        xau_i_present=xau_i_present,
        history=history,
    )
    cost = evaluate_cost_gate(
        prior35,
        attached=attached,
        m5_days=days,
        ticks_observed=bool(bidask_stats.get("available")),
        history=history,
        xau_i_present=xau_i_present,
    )

    prev_days = 14.88
    prev_events = 6
    comparison = [
        {
            "requirement": "M5 horizon",
            "previous": f"{prev_days}d frozen",
            "phase38": f"{days:.2f}d" if days else "0 / not collected",
            "improvement": "YES" if days > prev_days + 0.5 else "NO",
            "status": "MET_PREFERRED" if days >= TARGET_DAYS else "MET_MIN" if days >= MIN_DAYS else "INSUFFICIENT",
        },
        {
            "requirement": "independent events",
            "previous": str(prev_events),
            "phase38": str(event_block.get("event_count") if event_block.get("event_count") is not None else "not_recounted"),
            "improvement": "YES" if int(event_block.get("event_count") or 0) > prev_events else "NO",
            "status": event_block.get("classification"),
        },
        {
            "requirement": "M15",
            "previous": "NOT_OBSERVED canonical",
            "phase38": collect_m15.get("status"),
            "improvement": "YES" if collect_m15.get("ok") else "NO",
            "status": collect_m15.get("status"),
        },
        {
            "requirement": "Bid/Ask",
            "previous": "27.26 sidecar OBSERVED ~15d; production PROXY",
            "phase38": bidask_stats.get("status"),
            "improvement": "YES" if bidask_stats.get("available") else "NO",
            "status": bidask_stats.get("grade") or bidask_stats.get("status"),
        },
        {
            "requirement": "spread",
            "previous": "PROXY / BLOCKED",
            "phase38": cost["components"]["spread"]["status"],
            "improvement": "NO",
            "status": cost["components"]["spread"]["status"],
        },
        {
            "requirement": "commission",
            "previous": "BLOCKED / UNKNOWN",
            "phase38": cost["components"]["commission"]["status"],
            "improvement": "NO",
            "status": "UNKNOWN" if history.get("all_gold_commission_zero") else cost["components"]["commission"]["status"],
        },
        {
            "requirement": "swap",
            "previous": "UNKNOWN historical / BROKER_RATE_ONLY current",
            "phase38": "BROKER_RATE_ONLY" if attached and xau_i_present else "UNKNOWN",
            "improvement": "NO" if not attached else "PARTIAL",
            "status": "BROKER_RATE_ONLY" if attached and xau_i_present else "UNKNOWN",
        },
        {
            "requirement": "slippage",
            "previous": "MODELED / 0 pairs",
            "phase38": f"{history.get('requested_vs_filled_pairs')} pairs",
            "improvement": "NO",
            "status": "MODELED",
        },
        {
            "requirement": "execution",
            "previous": "DEAL_FILL_TAPE_ONLY",
            "phase38": history.get("grade"),
            "improvement": "NO",
            "status": history.get("grade"),
        },
        {
            "requirement": "symbol binding",
            "previous": "EV-EQ-01 NOT_PROVEN",
            "phase38": "NOT_PROVEN",
            "improvement": "NO",
            "status": "NOT_PROVEN",
        },
        {
            "requirement": "cost completeness",
            "previous": "INCOMPLETE 0/8",
            "phase38": f"{cost['complete_count']}/8 {cost['classification']}",
            "improvement": "NO" if not cost["cost_ready_for_validation"] else "YES",
            "status": cost["classification"],
        },
        {
            "requirement": "statistical sufficiency",
            "previous": "INSUFFICIENT_SAMPLE",
            "phase38": (
                "EVENT_SAMPLE_MET (n>=30 mechanical events; not a significance test)"
                if event_block.get("classification") == "SUFFICIENT"
                else "INSUFFICIENT"
            ),
            "improvement": "YES" if event_block.get("classification") == "SUFFICIENT" else "NO",
            "status": (
                "EVENT_SAMPLE_MET"
                if event_block.get("classification") == "SUFFICIENT"
                else event_block.get("classification")
            ),
        },
    ]

    blockers = [
        days < MIN_DAYS,
        int(event_block.get("event_count") or 0) < MIN_EVENTS,
        not cost["cost_ready_for_validation"],
        True,  # EV-EQ-01
    ]
    blocker_remaining = "YES" if any(blockers) else "NO"

    if attach.get("status") == "AUTH_REQUIRED":
        status = "AUTH_REQUIRED"
    elif attach.get("status") == "MT5_NOT_INSTALLED":
        status = "MT5_NOT_INSTALLED"
    elif attached and days >= TARGET_DAYS:
        status = "PASS"
    elif attached:
        status = "PASS_WITH_DEFERRAL"
    else:
        status = "BLOCKED"

    env_label = str(attach.get("environment") or UNKNOWN)
    real_interaction = "READ_ONLY" if attached and env_label == "REAL" else ("NONE" if not attached else f"READ_ONLY_{env_label}")

    discovery_summary = (
        f"Installed={discovery.get('installed')}; running_before={discovery.get('terminal64_running')}; "
        f"selected={selected_exe}; launch={launch}; attach={attach.get('status')}."
    )
    acquired_summary = (
        f"M5 days={days:.4f} rows={collect_m5.get('rows') or 0}; "
        f"M15={collect_m15.get('status')}; M1={collect_m1.get('status')}; "
        f"ticks={collect_ticks.get('status')}; bidask={bidask_stats.get('status')}; "
        f"history deals={history.get('deals')} orders={history.get('orders')} pairs={history.get('requested_vs_filled_pairs')}."
    )
    n_ev = event_block.get("event_count")
    missing_summary = (
        "60/180d XAUUSD_i tape still missing; " if days < MIN_DAYS else "M5 preferred 180d horizon met on research tape; "
    ) + (
        f"event floor met ({n_ev}>={MIN_EVENTS}); "
        if isinstance(n_ev, int) and n_ev >= MIN_EVENTS
        else f"events {n_ev}<{MIN_EVENTS}; "
    ) + (
        "cost AND-gate not COMPLETE; EV-EQ-01 NOT_PROVEN; "
        "commission not VERIFIED_SCHEDULE; slippage MODELED; requested/fill pairs 0. "
        "RAW expectancy is theoretical and is not a profitability verdict."
    )

    recommended = (
        "If AUTH_REQUIRED: operator must already-login the LiteFinance terminal (do not paste secrets into chat). "
        "If tape still <60d after a logged-in attach: broker history is the limit — do not merge logical XAUUSD. "
        "Do not start Phase 39 automatically. Do not optimize."
    )
    if attached and days >= MIN_DAYS and int(event_block.get("event_count") or 0) >= MIN_EVENTS:
        recommended = (
            "Phase 39 candidate (operator-initiated only): research walk-forward / statistical "
            "re-evaluation on the phase38 XAUUSD_i tape. Cost completeness remains INCOMPLETE. "
            "Do not start Phase 39 automatically. Do not optimize. Do not trade."
        )
    elif days >= MIN_DAYS:
        recommended = (
            "M5 horizon floor is met on a new research tape. Recounted events remain below 30 "
            "and/or cost completeness is INCOMPLETE. Next: operator-initiated Phase 39 only if "
            "the remaining cost/event gaps have an identified source. Do not merge logical XAUUSD. "
            "Do not optimize. Do not trade."
        )

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    ok_immut, issues = verify_immutability(before, base_dir=root)
    issues = _filter_immutability_issues(issues)
    ok_immut = (len(issues) == 0) and (fp_after == frozen_fp)
    binding = classify_dataset_binding(CANONICAL_SYMBOL, configured_symbol=PRIMARY_SYMBOL, dataset_symbol_map={})

    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": status,
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
        "mt5_discovery": {
            "installations": discovery,
            "selection": selection,
            "launch": launch,
            "attach": {k: v for k, v in attach.items() if k != "symbols"},
        },
        "symbols": {"XAUUSD_i": xau_i, "XAUUSD": xau},
        "m5": {
            "path": PHASE38_M5 if (root / PHASE38_M5).is_file() else None,
            "status": collect_m5.get("status"),
            "start": collect_m5.get("start"),
            "end": collect_m5.get("end"),
            "days": days,
            "rows": collect_m5.get("rows") or 0,
            "coverage": m5_audit,
            "strategy_windows": windows,
            "partial": collect_m5.get("partial"),
            "error": collect_m5.get("error"),
            "cap_hit": collect_m5.get("cap_hit"),
            "reused_existing_phase38_tape": collect_m5.get("reused_existing_phase38_tape"),
            "frozen_canonical_not_written": True,
        },
        "m15": {"path": PHASE38_M15 if (root / PHASE38_M15).is_file() else None, **{k: collect_m15.get(k) for k in ("status", "rows", "ok", "error", "duration_days")}},
        "m1": {"path": PHASE38_M1 if (root / PHASE38_M1).is_file() else None, **{k: collect_m1.get(k) for k in ("status", "rows", "ok", "error", "duration_days")}},
        "ticks": {"path": PHASE38_TICKS if (root / PHASE38_TICKS).is_file() else None, **{k: collect_ticks.get(k) for k in ("status", "rows", "ok", "error", "partial", "resource_bound")}},
        "bid_ask": {
            "path": PHASE38_BIDASK if (root / PHASE38_BIDASK).is_file() else None,
            "status": bidask_stats.get("status"),
            "grade": bidask_stats.get("grade"),
            "not_proxy": True,
            "stats": bidask_stats if bidask_stats.get("available") else None,
            "prior_sidecar_27_26": "logs/phase27_26_xauusd_i_m5_bidask.parquet",
        },
        "commission": {
            "status": "UNKNOWN",
            "verified_schedule": False,
            "all_deal_zeros": history.get("all_gold_commission_zero"),
            "zero_is_not_verified": True,
            "gold_deals": history.get("gold_deals"),
        },
        "swap": {
            "classification": "BROKER_RATE_ONLY" if attached and xau_i_present else "UNKNOWN",
            "current_swap_long": xau_i.get("swap_long"),
            "current_swap_short": xau_i.get("swap_short"),
            "historical": "UNKNOWN",
            "deal_zeros_prove_historical_zero": False,
        },
        "slippage": {
            "status": "MODELED",
            "genuine_requested_vs_executed_pairs": int(history.get("requested_vs_filled_pairs") or 0),
            "mt5_deviation_is_realized_slippage": False,
            "price_open_is_requested": False,
        },
        "execution": {
            "grade": history.get("grade"),
            "deals": history.get("deals"),
            "orders": history.get("orders"),
            "positions_touched": False,
            "orders_modified": False,
        },
        "dataset_binding": {
            "canonical_symbol": CANONICAL_SYMBOL,
            "dataset_symbol_map": {},
            "empty_map": True,
            "xauusd_merged": False,
            "logical_tapes_not_used": list(BLOCKED_LOGICAL_TAPES),
            "ev_eq_01": "NOT_PROVEN",
            "binding": binding.to_dict(),
        },
        "cost_completeness": cost,
        "event_sufficiency": event_block,
        "strategy_evaluation": strategy_block,
        "comparison": comparison,
        "BLOCKER_REMAINING": blocker_remaining,
        "discovery_summary": discovery_summary,
        "acquired_summary": acquired_summary,
        "missing_summary": missing_summary,
        "recommended_next_phase": recommended,
        "fingerprints": {
            "phase28_m5_file": frozen_fp,
            "phase28_m5_content": frozen_content,
            "phase28_m5_unchanged": fp_after == frozen_fp == EXPECTED_CANONICAL_FINGERPRINT,
            "phase38_m5_file": (wrote.get("m5") or {}).get("file_fingerprint"),
            "phase38_m5_content": (wrote.get("m5") or {}).get("content_fingerprint"),
        },
        "wrote": wrote,
        "datasets_changed": fp_after != frozen_fp,
        "immutability_ok": ok_immut and fp_after == frozen_fp,
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
            "PHASE_39_STARTED": False,
        },
        "phase_39_started": False,
        "next_step": "STOP. Do not start Phase 39. Do not optimize. Do not trade.",
    }
    _write_json(root / PHASE38_JSON, payload)
    _write_markdown(root, payload)
    _patch_truth_docs(root, status=status)
    if file_fingerprint(root / CANONICAL_PARQUET) != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Phase 38 mutated the frozen canonical M5 parquet")
    return payload


def pd_ts_end(frame: Any) -> datetime | None:
    if frame is None or len(frame) == 0:
        return None
    ts = frame.index[-1]
    try:
        return ts.to_pydatetime()
    except Exception:
        return None


if __name__ == "__main__":
    run_phase38_collection()
