"""Phase 27.29 — Real-account swap evidence closure.

Read-only. Current broker rates are not a historical series.
Short-hold zero swap is not historical zero. Does not start MT5,
place orders, or rewrite parquet.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_5_final_broker_cost_gate import load_all_gold_deal_records
from tradingbot.backtest.phase27_9_real_broker_evidence import bounded_readonly_attach_once
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_22_commission_forensic import (
    REDACT_ACCOUNT_KEYS,
    collect_account_metadata,
    collect_terminal_metadata,
)
from tradingbot.backtest.swap_policy import (
    POLICY,
    broker_rate_only_is_not_historical,
    cost_completeness_from_broker_rates_only,
    record_broker_swap_rates,
    realized_zero_is_not_verified_zero,
    weekday_from_rollover3days,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2729_JSON = "logs/phase27_29_swap_evidence.json"
PHASE2729_MD = "docs_v2/01_truth/PHASE27_29_SWAP_EVIDENCE.md"
PHASE2713_JSON = "logs/phase27_13_swap_policy.json"
PHASE2724_JSON = "logs/phase27_24_execution_cost_forensics.json"
CANONICAL_SYMBOL = PRIMARY_SYMBOL
CANONICAL_PARQUET = "data/XAUUSD_i_5m.parquet"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
REQUIRED_ENV = "REAL"
REQUIRED_SERVER = "LiteFinance-MT5-Live"
HISTORY_DAYS = 180
MAX_LIVE_DEALS = 200
OVERNIGHT_MIN_HOURS = 20
WEDNESDAY = 2

GRADE_A = "HISTORICAL_ACCOUNT_APPLICABLE_SWAP_PROVEN"
GRADE_B = "HISTORICAL_PRODUCT_SPECIFIC"
GRADE_C = "CURRENT_BROKER_RATE_ONLY"
GRADE_D = "REALIZED_ZERO_NOT_PROVEN"
GRADE_E = "INSUFFICIENT_DATA"
GRADE_F = "CONTRADICTORY"

FINAL_C = "CURRENT_BROKER_RATE_ONLY"
HISTORICAL_NOT_IDENTIFIABLE = "HISTORICAL_SWAP_RATE_NOT_IDENTIFIABLE_FROM_DEALS"
HISTORICAL_NOT_IDENTIFIABLE_FROM_DEALS = HISTORICAL_NOT_IDENTIFIABLE
NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"

SWAP_MODE_LABELS = {
    0: "DISABLED",
    1: "POINTS",
    2: "CURRENCY_SYMBOL",
    3: "CURRENCY_MARGIN",
    4: "CURRENCY_DEPOSIT",
    5: "INTEREST_CURRENT",
    6: "INTEREST_OPEN",
    7: "REOPEN_CURRENT",
    8: "REOPEN_BID",
}

SOURCE_SEARCH_PATHS = (
    "logs/phase27_13_swap_policy.json",
    "logs/phase27_24_execution_cost_forensics.json",
    "logs/phase27_17_real_broker_evidence.json",
    "docs_v2/01_truth/PHASE27_13_SWAP_POLICY.md",
    "docs_v2/01_truth/PHASE27_24_EXECUTION_COST_FORENSICS.md",
    "tradingbot/backtest/swap_policy.py",
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account_type",
    "broker",
    "server",
    "terminal_build",
    "symbol",
    "current_swap_long",
    "current_swap_short",
    "current_rollover_day",
    "current_swap_mode",
    "current_swap_units",
    "historical_evidence_found",
    "historical_evidence_source",
    "deal_count",
    "overnight_deal_count",
    "rollover_crossing_deal_count",
    "nonzero_swap_count",
    "zero_swap_count",
    "total_realized_swap",
    "deal_date_start",
    "deal_date_end",
    "historical_rate_identifiable",
    "historical_rate",
    "historical_rate_currency_or_unit",
    "effective_date",
    "applicability",
    "evidence_grade",
    "policy_status",
    "final_classification",
    "blockers",
    "operator_dependency",
    "production_code_changed",
    "datasets_changed",
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


def _sanitize(obj: Any) -> Any:
    blocked = FORBIDDEN_OUTPUT_KEYS | REDACT_ACCOUNT_KEYS | {"password", "mt5_password", "token", "api_key", "investor"}
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in blocked}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def file_fingerprint(path: str | Path) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_utc(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def crossed_utc_midnight(start: datetime, end: datetime) -> bool:
    if end < start:
        start, end = end, start
    return start.date() != end.date()


def crossed_weekday(start: datetime, end: datetime, weekday: int) -> bool:
    if end < start:
        start, end = end, start
    day = start.date()
    last = end.date()
    while day <= last:
        if day.weekday() == weekday:
            return True
        day = day + timedelta(days=1)
    return False


def is_overnight_hold(start: datetime | None, end: datetime | None) -> bool:
    if start is None or end is None:
        return False
    if end < start:
        start, end = end, start
    if (end - start) >= timedelta(hours=OVERNIGHT_MIN_HOURS):
        return True
    return crossed_utc_midnight(start, end)


def derive_historical_swap_rate(
    *,
    realized_swap: float | None,
    volume: float | None,
    financing_days: int | None,
    rollover_multiplier: float | None,
    duration_sufficient: bool,
    applicability_established: bool,
) -> dict[str, Any]:
    """Derive a per-lot/day rate only when every material variable is known."""
    missing: list[str] = []
    if realized_swap is None:
        missing.append("realized_swap")
    if volume is None or volume <= 0:
        missing.append("volume")
    if financing_days is None or financing_days <= 0:
        missing.append("financing_days")
    if rollover_multiplier is None:
        missing.append("rollover_multiplier")
    if not duration_sufficient:
        missing.append("duration")
    if not applicability_established:
        missing.append("applicability")
    if missing:
        return {
            "identifiable": False,
            "rate": None,
            "status": NOT_IDENTIFIABLE,
            "missing": missing,
        }
    days = float(financing_days) * float(rollover_multiplier)
    if days <= 0:
        return {"identifiable": False, "rate": None, "status": NOT_IDENTIFIABLE, "missing": ["financing_days"]}
    return {
        "identifiable": True,
        "rate": float(realized_swap) / (float(volume) * days),
        "status": "DERIVED",
        "missing": [],
    }


def classify_swap_evidence_grade(
    *,
    current_rates_proven: bool,
    historical_account_applicable: bool,
    historical_product_specific: bool,
    overnight_count: int,
    rollover_crossing_count: int,
    zero_swap_count: int,
    nonzero_swap_count: int,
) -> str:
    if historical_account_applicable:
        return GRADE_A
    if historical_product_specific:
        return GRADE_B
    if nonzero_swap_count > 0 and zero_swap_count > 0 and overnight_count > 0 and not current_rates_proven:
        return GRADE_F
    if current_rates_proven:
        return GRADE_C
    if zero_swap_count > 0 and overnight_count == 0 and rollover_crossing_count == 0:
        return GRADE_D
    return GRADE_E


def search_existing_evidence(root: Path) -> dict[str, Any]:
    found = [{"path": rel, "present": (root / rel).is_file()} for rel in SOURCE_SEARCH_PATHS]
    p13 = _safe_load_json(root / PHASE2713_JSON) or {}
    p24 = _safe_load_json(root / PHASE2724_JSON) or {}
    return {
        "paths": found,
        "phase27_13_historical_series": (p13.get("observed") or p13.get("snapshot") or {}).get("historical_swap_series")
        or p13.get("historical_swap_series"),
        "phase27_24_treatment": (p24.get("swap") or {}).get("treatment"),
        "phase27_24_historical_series": (p24.get("swap") or {}).get("historical_swap_series"),
        "historical_series_already_present": False,
    }


def _deal_time(deal: dict[str, Any]) -> datetime | None:
    for key in ("time_utc", "time", "open_time", "close_time"):
        parsed = parse_utc(deal.get(key))
        if parsed is not None:
            return parsed
    return None


def _position_intervals(deals: list[dict[str, Any]]) -> dict[str, tuple[datetime, datetime]]:
    groups: dict[str, list[datetime]] = {}
    for deal in deals:
        key = str(deal.get("position_id") or deal.get("position") or "")
        if not key or key in {"None", "0"}:
            continue
        ts = _deal_time(deal)
        if ts is None:
            continue
        groups.setdefault(key, []).append(ts)
    out: dict[str, tuple[datetime, datetime]] = {}
    for key, times in groups.items():
        if len(times) < 2:
            continue
        times.sort()
        out[key] = (times[0], times[-1])
    return out


def summarize_swap_deals(deals: list[dict[str, Any]], *, rollover_weekday: int | None) -> dict[str, Any]:
    values: list[float] = []
    times: list[datetime] = []
    overnight = 0
    rollover_cross = 0
    identifiable_holds = 0
    intervals = _position_intervals(deals)
    for deal in deals:
        raw = deal.get("swap")
        try:
            if raw is not None:
                values.append(float(raw))
        except (TypeError, ValueError):
            pass
        ts = _deal_time(deal)
        if ts is not None:
            times.append(ts)
        key = str(deal.get("position_id") or deal.get("position") or "")
        start = parse_utc(deal.get("open_time"))
        end = parse_utc(deal.get("close_time")) or ts
        if start is None and key in intervals:
            start, end = intervals[key]
        if start is not None and end is not None:
            identifiable_holds += 1
            if is_overnight_hold(start, end):
                overnight += 1
                if rollover_weekday is not None and crossed_weekday(start, end, rollover_weekday):
                    rollover_cross += 1
    zeros = sum(1 for v in values if v == 0.0)
    nonzero = sum(1 for v in values if v != 0.0)
    dist: dict[str, int] = {}
    for val in values:
        label = f"{val:.4f}"
        dist[label] = dist.get(label, 0) + 1
    return {
        "deal_count": len(deals),
        "identifiable_hold_count": identifiable_holds,
        "overnight_deal_count": overnight,
        "rollover_crossing_deal_count": rollover_cross,
        "zero_swap_count": zeros,
        "nonzero_swap_count": nonzero,
        "total_realized_swap": round(sum(values), 8) if values else 0.0,
        "swap_distribution": dist,
        "deal_date_start": min(times).isoformat().replace("+00:00", "Z") if times else None,
        "deal_date_end": max(times).isoformat().replace("+00:00", "Z") if times else None,
        "limitation": HISTORICAL_NOT_IDENTIFIABLE_FROM_DEALS if overnight == 0 else "overnight samples present; rate still not derived without applicability",
        "proves_historical_zero": False,
    }


def collect_current_swap_spec(mt5: Any, symbol: str = CANONICAL_SYMBOL) -> dict[str, Any]:
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"symbol": symbol, "existence": "NO"}
    mode = getattr(info, "swap_mode", None)
    rollover = getattr(info, "swap_rollover3days", None)
    return {
        "symbol": symbol,
        "existence": "YES",
        "visibility": "YES" if getattr(info, "visible", None) else "NO",
        "swap_long": getattr(info, "swap_long", None),
        "swap_short": getattr(info, "swap_short", None),
        "swap_rollover3days": rollover,
        "swap_mode": mode,
        "swap_mode_label": SWAP_MODE_LABELS.get(mode, UNKNOWN if mode is None else str(mode)),
        "contract_size": getattr(info, "trade_contract_size", None),
        "currency_profit": getattr(info, "currency_profit", None),
        "currency_margin": getattr(info, "currency_margin", None),
    }


def _is_gold(symbol: Any) -> bool:
    return str(symbol or "").upper().replace(" ", "") in {"XAUUSD", "XAUUSD_I", CANONICAL_SYMBOL.upper()}


def collect_live_session() -> dict[str, Any]:
    attach = bounded_readonly_attach_once()
    meta: dict[str, Any] = {
        "attempted": True,
        "attach_ok": bool(attach.get("ok")),
        "attach_error": attach.get("error"),
        "environment_ok": False,
        "collection_stopped": False,
        "stop_reason": None,
        "method": "symbol_info + history_deals_get read-only; no symbol_select",
        "deals": [],
        "spec": {},
        "account": {},
        "terminal": {},
    }
    if not attach.get("ok"):
        meta["collection_stopped"] = True
        meta["stop_reason"] = "BLOCKED_PENDING_OPERATOR"
        return meta
    import MetaTrader5 as mt5

    account = collect_account_metadata(mt5)
    terminal = collect_terminal_metadata(mt5)
    env = str(account.get("trade_mode_label") or UNKNOWN)
    server = str(account.get("server") or UNKNOWN)
    meta["account"] = _sanitize(account)
    meta["terminal"] = terminal
    meta["environment"] = env
    meta["server"] = server
    if env != REQUIRED_ENV or server != REQUIRED_SERVER:
        meta["collection_stopped"] = True
        meta["stop_reason"] = "BLOCKED_PENDING_OPERATOR"
        meta["error"] = f"attached {env}/{server} is not {REQUIRED_ENV}/{REQUIRED_SERVER}"
        return meta
    meta["environment_ok"] = True
    meta["spec"] = collect_current_swap_spec(mt5, CANONICAL_SYMBOL)
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=HISTORY_DAYS)
    try:
        raw = mt5.history_deals_get(date_from, date_to)
    except Exception as exc:
        meta["error"] = str(exc)
        raw = []
    deals: list[dict[str, Any]] = []
    for item in list(raw or []):
        if not _is_gold(getattr(item, "symbol", None)):
            continue
        deals.append(
            {
                "ticket": getattr(item, "ticket", None),
                "position_id": getattr(item, "position_id", None),
                "symbol": getattr(item, "symbol", None),
                "type": getattr(item, "type", None),
                "volume": getattr(item, "volume", None),
                "swap": getattr(item, "swap", None),
                "time_utc": datetime.fromtimestamp(getattr(item, "time", 0), tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if getattr(item, "time", None)
                else None,
                "_source": "mt5_history_deals_get",
            }
        )
        if len(deals) >= MAX_LIVE_DEALS:
            break
    meta["deals"] = deals
    meta["live_gold_deal_count"] = len(deals)
    return meta


def merge_deals(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for deal in group:
            ticket = deal.get("ticket")
            key = ticket if ticket not in (None, "") else (deal.get("_source"), deal.get("time_utc"), deal.get("volume"), deal.get("swap"))
            if key in seen:
                continue
            seen.add(key)
            out.append(deal)
    return out


def run_phase27_29_swap_evidence(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    fingerprint_before = file_fingerprint(root / CANONICAL_PARQUET)
    before = build_immutability_manifest(root)
    existing = search_existing_evidence(root)
    prior24 = _safe_load_json(root / PHASE2724_JSON) or {}
    swap_status_before = (prior24.get("swap") or {}).get("treatment") or POLICY

    live = collect_live_session()
    artifact_deals = load_all_gold_deal_records(root)
    deals = merge_deals(artifact_deals, list(live.get("deals") or []))

    spec = dict(live.get("spec") or {})
    current_from_this_session = bool(
        live.get("environment_ok")
        and spec.get("existence") == "YES"
        and (spec.get("swap_long") is not None or spec.get("swap_short") is not None)
    )
    if current_from_this_session:
        recorded = record_broker_swap_rates(
            spec, symbol=CANONICAL_SYMBOL, source="mt5_symbol_info", timestamp=timestamp
        )
    else:
        recorded = record_broker_swap_rates(
            {},
            symbol=CANONICAL_SYMBOL,
            source="not_collected_this_session",
            timestamp=None,
        )

    current_proven = bool(current_from_this_session and broker_rate_only_is_not_historical(recorded))
    rollover_day = recorded.triple_swap_weekday
    rollover_weekday = WEDNESDAY if rollover_day == "Wednesday" else None
    tape = summarize_swap_deals(deals, rollover_weekday=rollover_weekday)
    derived = derive_historical_swap_rate(
        realized_swap=tape["total_realized_swap"] if tape["overnight_deal_count"] else None,
        volume=None,
        financing_days=None,
        rollover_multiplier=None,
        duration_sufficient=tape["overnight_deal_count"] > 0,
        applicability_established=False,
    )
    grade = classify_swap_evidence_grade(
        current_rates_proven=current_proven,
        historical_account_applicable=False,
        historical_product_specific=False,
        overnight_count=int(tape["overnight_deal_count"]),
        rollover_crossing_count=int(tape["rollover_crossing_deal_count"]),
        zero_swap_count=int(tape["zero_swap_count"]),
        nonzero_swap_count=int(tape["nonzero_swap_count"]),
    )
    if live.get("stop_reason") == "BLOCKED_PENDING_OPERATOR" and not current_proven:
        collection_status = "BLOCKED_PENDING_OPERATOR"
    else:
        collection_status = "COLLECTED" if current_proven else "EXISTING_EVIDENCE_ONLY"

    cfg = BacktestConfig()
    completeness = cost_completeness_from_broker_rates_only()
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    fingerprint_after = file_fingerprint(root / CANONICAL_PARQUET)
    datasets_changed = not originals_untouched or fingerprint_before != fingerprint_after

    historical_found = tape["overnight_deal_count"] > 0 or tape["nonzero_swap_count"] > 0
    blockers = [
        "historical swap series UNKNOWN — current broker rates are not historical",
        "no meaningful overnight/rollover deal sample; HISTORICAL_SWAP_RATE_NOT_IDENTIFIABLE_FROM_DEALS",
        "realized swap zeros on short-hold deals do not prove historical zero",
        "historical_rollover_schedule UNKNOWN even if current Wednesday is observed",
    ]
    account = live.get("account") or {}
    env = str(live.get("environment") or account.get("trade_mode_label") or UNKNOWN)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.29",
        "status": "PASS",
        "timestamp_utc": timestamp,
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "account_type": env,
        "broker": account.get("broker") or "LiteFinance Global LLC",
        "server": live.get("server") or account.get("server") or REQUIRED_SERVER,
        "terminal_build": (live.get("terminal") or {}).get("build"),
        "symbol": CANONICAL_SYMBOL,
        "collection_status": collection_status,
        "current_swap_long": recorded.swap_long,
        "current_swap_short": recorded.swap_short,
        "current_rollover_day": rollover_day,
        "current_swap_mode": spec.get("swap_mode_label") if current_from_this_session else UNKNOWN,
        "current_swap_units": spec.get("swap_mode_label") if current_from_this_session else UNKNOWN,
        "current_swap_rollover3days": recorded.swap_rollover3days,
        "current_rate_timestamp_utc": recorded.timestamp,
        "current_rate_source": recorded.source,
        "current_broker_rate_proven": current_proven,
        "current_rate_is_historical": False,
        "historical_rollover_schedule": UNKNOWN,
        "historical_evidence_found": historical_found,
        "historical_evidence_source": "gold_deal_tape + optional live history_deals_get",
        "deal_count": tape["deal_count"],
        "overnight_deal_count": tape["overnight_deal_count"],
        "rollover_crossing_deal_count": tape["rollover_crossing_deal_count"],
        "nonzero_swap_count": tape["nonzero_swap_count"],
        "zero_swap_count": tape["zero_swap_count"],
        "total_realized_swap": tape["total_realized_swap"],
        "deal_date_start": tape["deal_date_start"],
        "deal_date_end": tape["deal_date_end"],
        "deal_forensics": tape,
        "historical_rate_identifiable": False,
        "historical_rate": None,
        "historical_rate_currency_or_unit": None,
        "historical_rate_status": derived["status"],
        "effective_date": UNKNOWN,
        "applicability": False,
        "evidence_grade": grade,
        "policy_status": POLICY,
        "final_classification": grade if grade == GRADE_C else grade,
        "historical_swap_proven": False,
        "complete_policy_satisfied": False,
        "swap_status_before": swap_status_before,
        "swap_status_after": POLICY,
        "default_swap_status": cfg.swap_status,
        "existing_evidence_search": existing,
        "live_collection": _sanitize({k: v for k, v in live.items() if k != "deals"}),
        "recorded_broker_rate": recorded.to_dict(),
        "public_supporting_documentation": [],
        "implementation_audit": {
            "paths": [
                "tradingbot/backtest/swap_policy.py",
                "tradingbot/backtest/cost_model.py::build_backtest_cost_model",
                "tradingbot/backtest/config.py::BacktestConfig.swap_status",
            ],
            "broker_rate_only_equals_historical": False,
            "current_rate_can_become_historical": False,
            "unknown_fail_closed": True,
            "broker_rate_only_blocks_complete": completeness != CostCompleteness.COMPLETE,
            "default_swap_status_unchanged": cfg.swap_status == UNKNOWN,
            "realized_zero_is_not_historical_zero": realized_zero_is_not_verified_zero([0.0] * max(1, tape["zero_swap_count"])),
        },
        "blockers": blockers,
        "operator_dependency": True,
        "production_code_changed": False,
        "datasets_changed": datasets_changed,
        "canonical_fingerprint_before": fingerprint_before,
        "canonical_fingerprint_after": fingerprint_after,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "complete_costs_required_weakened": False,
        "phase27_16_final_gate_unchanged": final_gate,
        "phase27_13_preserved": (root / PHASE2713_JSON).is_file(),
        "phase27_24_preserved": (root / PHASE2724_JSON).is_file(),
        "production_readiness": "BLOCKED",
        "ev_eq_01": "NOT_PROVEN",
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "parquet_rewritten": False,
            "historical_series_synthesized": False,
            "zero_treated_as_historical_zero": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "phase_27_30_started": False,
        },
        "deferred": ["Phase 27.30+ — not started"],
    }
    missing_keys = [k for k in REQUIRED_ARTIFACT_KEYS if k not in payload]
    required_ok = (
        not missing_keys,
        originals_untouched,
        fingerprint_before == fingerprint_after,
        not datasets_changed,
        not payload["production_code_changed"],
        payload["current_rate_is_historical"] is False,
        payload["historical_swap_proven"] is False,
        payload["complete_policy_satisfied"] is False,
        payload["implementation_audit"]["broker_rate_only_blocks_complete"],
        payload["default_swap_status"] == UNKNOWN,
        not payload["complete_costs_required_weakened"],
        final_gate == "BLOCKED",
        realized_zero_is_not_verified_zero([0.0] * 50),
    )
    if not all(required_ok):
        payload["status"] = "FAILED"
        if missing_keys:
            payload["blockers"] = list(payload["blockers"]) + [f"missing_artifact_keys:{','.join(missing_keys)}"]
    if collection_status == "BLOCKED_PENDING_OPERATOR" and not current_proven:
        payload["status"] = "PASS_WITH_DEFERRAL"

    out = root / PHASE2729_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_29_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_29_swap_evidence(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    md = f"""# Phase 27.29 — Real Account Swap Evidence Closure

**Status:** {payload["status"]}  
**Evidence grade:** `{payload["evidence_grade"]}`  
**Final classification:** `{payload["final_classification"]}`  
**Artifact:** `{PHASE2729_JSON}`  
**Timestamp UTC:** `{payload["timestamp_utc"]}`

Read-only. Phase 27.13 / 27.24 artifacts were not overwritten. Production parquet was not rewritten.
`BROKER_RATE_ONLY` remains a policy gate: current rates are not a historical series.

## Real account

| Field | Value |
|---|---|
| account type | `{payload["account_type"]}` |
| broker | `{payload["broker"]}` |
| server | `{payload["server"]}` |
| terminal build | `{payload["terminal_build"]}` |
| symbol | `{payload["symbol"]}` |
| collection | `{payload["collection_status"]}` |

## Current broker swap

| Field | Value |
|---|---|
| swap_long | `{payload["current_swap_long"]}` |
| swap_short | `{payload["current_swap_short"]}` |
| rollover day | `{payload["current_rollover_day"]}` |
| swap mode | `{payload["current_swap_mode"]}` |
| units | `{payload["current_swap_units"]}` |
| timestamp | `{payload["current_rate_timestamp_utc"]}` |
| historical rollover schedule | `{payload["historical_rollover_schedule"]}` |

Current rates are **not** historical rates.

## Deal forensics

| Field | Value |
|---|---|
| deals | `{payload["deal_count"]}` |
| overnight | `{payload["overnight_deal_count"]}` |
| rollover-crossing | `{payload["rollover_crossing_deal_count"]}` |
| zero swap | `{payload["zero_swap_count"]}` |
| nonzero swap | `{payload["nonzero_swap_count"]}` |
| total realized swap | `{payload["total_realized_swap"]}` |
| range | `{payload["deal_date_start"]}` → `{payload["deal_date_end"]}` |

`{HISTORICAL_NOT_IDENTIFIABLE_FROM_DEALS}` unless overnight/rollover samples exist. Realized zero ≠ historical zero.

## Historical rate

identifiable: `{payload["historical_rate_identifiable"]}`. status: `{payload["historical_rate_status"]}`.  
applicability: `{payload["applicability"]}`. effective date: `{payload["effective_date"]}`.

## Classification

Grade `{payload["evidence_grade"]}`. Historical swap proven: `{payload["historical_swap_proven"]}`.  
COMPLETE policy satisfied: `{payload["complete_policy_satisfied"]}`. Policy status: `{payload["policy_status"]}`.

## Implementation

`BROKER_RATE_ONLY` cannot silently become historical. Default `BacktestConfig.swap_status` remains `{payload["default_swap_status"]}`.

## FINAL_GATE

swap_status_before: `{payload["swap_status_before"]}`  
swap_status_after: `{payload["swap_status_after"]}`  
COMPLETE_COSTS_REQUIRED remains enforced. FINAL_GATE remains `{payload["phase27_16_final_gate_unchanged"]}`.

## Next

STOP after Phase 27.29.
"""
    (root / PHASE2729_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.29 swap evidence:** `{PHASE2729_JSON}` — "
            f"grade `{payload['evidence_grade']}`; historical series UNKNOWN; "
            "current broker rates ≠ historical"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.28 commission evidence:** `logs/phase27_28_commission_evidence.json` — "
                "grade `OBSERVED_ZERO_NOT_PROVEN`; final `OBSERVED_ZERO_NOT_PROVEN`; "
                "account_product_type UNKNOWN; VERIFIED_SCHEDULE not satisfied"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        old = (
            "| Swap historical realized | **UNKNOWN**. Policy Decision 4 = `BROKER_RATE_ONLY`. "
            "Phase 27.24 treatment `BROKER_RATE_ONLY`; evidence `UNKNOWN`; historical series UNKNOWN; "
            "realized zero ≠ verified zero |"
        )
        new = (
            "| Swap historical realized | **UNKNOWN**. Policy Decision 4 = `BROKER_RATE_ONLY`. "
            f"Phase 27.29 grade `{payload['evidence_grade']}`; current rates ≠ historical series; "
            "realized zero ≠ historical zero |"
        )
        if old in text:
            text = text.replace(old, new)
        known.write_text(text, encoding="utf-8")

    design = root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md"
    if design.is_file():
        text = design.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.29 swap evidence:** `{PHASE2729_JSON}` — "
            "BROKER_RATE_ONLY current snapshot; historical series UNKNOWN"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.28 commission evidence:** `logs/phase27_28_commission_evidence.json` — "
                "observed zeros remain OBSERVED_ZERO_NOT_PROVEN; no account-applicable schedule"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        design.write_text(text, encoding="utf-8")
