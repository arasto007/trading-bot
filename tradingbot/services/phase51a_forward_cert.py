"""Phase 51A — real forward demo certification (PA+Meta live evidence)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import _profit_factor

ROOT = Path(__file__).resolve().parents[2]
PHASE51A_DIR = ROOT / "logs" / "phase51a"
TRADES_PATH = PHASE51A_DIR / "trades.jsonl"
EVENTS_PATH = PHASE51A_DIR / "events.jsonl"
START_PATH = PHASE51A_DIR / "forward_start.json"
RESULT_PATH = ROOT / "logs" / "phase51a_forward_result.txt"
PENDING_PATH = PHASE51A_DIR / "pending_entries.json"

_MAGIC = 234000
MIN_SAMPLE = 3
TARGET_DAYS = 5
PF_GATE = 1.3
EXP_R_GATE = 0.20
MAX_DD_GATE = 3.0


def is_phase51a_enabled() -> bool:
    return os.getenv("PHASE51A_FORWARD_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def _utc_day(day: datetime | None = None) -> datetime:
    d = day or datetime.now(timezone.utc)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts_raw: str) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return None


def _after_forward_start(ts_raw: str) -> bool:
    if not START_PATH.is_file():
        return True
    try:
        data = json.loads(START_PATH.read_text(encoding="utf-8"))
        recorded = data.get("recorded_at")
        if recorded:
            start = _parse_ts(str(recorded))
            if start and _parse_ts(ts_raw):
                return _parse_ts(ts_raw) >= start  # type: ignore[operator]
        day = str(data.get("start_date", ""))
        if day:
            start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts = _parse_ts(ts_raw)
            return ts >= start if ts else False
    except Exception:
        pass
    return True


def ensure_forward_start(*, force: bool = False) -> str:
    PHASE51A_DIR.mkdir(parents=True, exist_ok=True)
    today = _utc_day().strftime("%Y-%m-%d")
    if START_PATH.is_file() and not force:
        try:
            return str(json.loads(START_PATH.read_text(encoding="utf-8")).get("start_date") or today)
        except Exception:
            pass
    START_PATH.write_text(
        json.dumps({"start_date": today, "recorded_at": _now_iso()}, indent=2),
        encoding="utf-8",
    )
    return today


def forward_start_date() -> str | None:
    if not START_PATH.is_file():
        return None
    try:
        return str(json.loads(START_PATH.read_text(encoding="utf-8")).get("start_date") or "")
    except Exception:
        return None


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path, *, tail: int = 50_000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            chunk = min(size, max(tail * 400, 65536))
            fh.seek(max(0, size - chunk))
            raw = fh.read().decode("utf-8", errors="replace")
        lines = raw.splitlines()[-tail:]
    except Exception:
        lines = path.read_text(encoding="utf-8").splitlines()[-tail:]
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_pending() -> dict[str, dict[str, Any]]:
    if not PENDING_PATH.is_file():
        return {}
    try:
        return json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_pending(data: dict[str, dict[str, Any]]) -> None:
    PHASE51A_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def log_event(event: str, **fields: Any) -> None:
    if not is_phase51a_enabled():
        return
    _append_jsonl(EVENTS_PATH, {"ts": _now_iso(), "event": event, **fields})


def log_order_send_failure(*, symbol: str, direction: str, message: str) -> None:
    log_event("order_send_failure", symbol=symbol, direction=direction, message=message)


def log_runtime_error(*, stage: str, message: str) -> None:
    log_event("runtime_error", stage=stage, message=message)


def update_trade_excursion(*, ticket: int, current_r: float) -> None:
    """Track running MFE/MAE (in R) while position is open."""
    if not is_phase51a_enabled():
        return
    pending = _load_pending()
    key = str(ticket)
    if key not in pending:
        return
    row = pending[key]
    mfe = float(row.get("_mfe_r") if row.get("_mfe_r") is not None else current_r)
    mae = float(row.get("_mae_r") if row.get("_mae_r") is not None else current_r)
    row["_mfe_r"] = round(max(mfe, current_r), 4)
    row["_mae_r"] = round(min(mae, current_r), 4)
    pending[key] = row
    _save_pending(pending)


def log_trade_entry(
    *,
    ticket: int,
    signal: Any,
    fill_price: float,
    lot: float,
) -> None:
    """Record Phase 51A entry fields at live execution."""
    if not is_phase51a_enabled():
        return
    meta = dict(getattr(signal, "metadata", None) or {})
    row = {
        "event": "trade_entry",
        "ticket": int(ticket),
        "timestamp": _now_iso(),
        "selected_engine": meta.get("selected_engine") or meta.get("router_engine", "PA"),
        "meta_probability": meta.get("meta_probability"),
        "direction": signal.direction.name,
        "entry_price": round(float(fill_price), 5),
        "stop_pips": meta.get("stop_pips"),
        "tp_price": round(float(signal.take_profit), 5) if signal.take_profit else None,
        "effective_risk_pct": meta.get("effective_risk_pct"),
        "lot": round(float(lot), 4),
        "symbol": signal.symbol,
        "timeframe": signal.timeframe,
        "strategy_name": signal.strategy_name,
    }
    _append_jsonl(TRADES_PATH, row)
    pending = _load_pending()
    pending[str(ticket)] = row
    _save_pending(pending)


def log_trade_exit(
    *,
    ticket: int,
    exit_reason: str,
    pnl_usd: float,
    pnl_r: float,
    exit_ts: str | None = None,
    mfe: float | None = None,
    mae: float | None = None,
) -> None:
    """Complete trade with exit fields."""
    if not is_phase51a_enabled():
        return
    pending = _load_pending()
    entry = pending.pop(str(ticket), pending.pop(str(abs(ticket)), {}))
    entry_ts = entry.get("timestamp") or exit_ts
    hold_minutes = 0.0
    if entry_ts and exit_ts:
        t0, t1 = _parse_ts(entry_ts), _parse_ts(exit_ts)
        if t0 and t1:
            hold_minutes = round((t1 - t0).total_seconds() / 60.0, 1)

    row = {
        "event": "trade_complete",
        "ticket": int(ticket),
        "entry": entry,
        "exit": {
            "timestamp": exit_ts or _now_iso(),
            "exit_reason": exit_reason,
            "pnl_usd": round(float(pnl_usd), 2),
            "pnl_R": round(float(pnl_r), 4),
            "hold_minutes": hold_minutes,
            "max_favorable_excursion": round(float(mfe if mfe is not None else entry.get("_mfe_r", 0) or 0), 4),
            "max_adverse_excursion": round(float(mae if mae is not None else entry.get("_mae_r", 0) or 0), 4),
        },
    }
    _append_jsonl(TRADES_PATH, row)
    _save_pending(pending)


def _completed_trades(since_start: bool = True) -> list[dict[str, Any]]:
    rows = _read_jsonl(TRADES_PATH)
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("event") != "trade_complete":
            continue
        exit_ts = (r.get("exit") or {}).get("timestamp", "")
        if since_start and not _after_forward_start(exit_ts):
            continue
        out.append(r)
    return out


def _count_meta_decisions(day: datetime) -> tuple[int, int, int]:
    from tradingbot.services.phase47c_forward_tracker import _read_jsonl as read_log

    path = ROOT / "data" / "meta_decisions.jsonl"
    start = _utc_day(day)
    end = start + timedelta(days=1)
    setups = accepted = rejected = 0
    router_path = ROOT / "logs" / "router_decisions.jsonl"
    for row in read_log(router_path, tail_lines=100_000):
        ts = row.get("logged_at") or row.get("timestamp") or ""
        t = _parse_ts(str(ts))
        if not t or not (start <= t < end) or not _after_forward_start(str(ts)):
            continue
        if str(row.get("pa_signal", "")).upper() in ("BUY", "SELL"):
            setups += 1
    for row in read_log(path, tail_lines=50_000):
        if "allowed" not in row:
            continue
        t = _parse_ts(str(row.get("ts", "")))
        if not t or not (start <= t < end) or not _after_forward_start(str(row.get("ts", ""))):
            continue
        if row.get("allowed"):
            accepted += 1
        else:
            rejected += 1
    return setups, accepted, rejected


def _quality_flags(day: datetime) -> dict[str, int]:
    start = _utc_day(day)
    end = start + timedelta(days=1)
    runtime = order_fail = abnormal = 0
    for row in _read_jsonl(EVENTS_PATH):
        t = _parse_ts(str(row.get("ts", "")))
        if not t or not (start <= t < end):
            continue
        ev = row.get("event")
        if ev == "runtime_error":
            runtime += 1
        elif ev == "order_send_failure":
            order_fail += 1
    from tradingbot.services.phase47c_forward_tracker import _count_abnormal_stops

    abnormal = _count_abnormal_stops(start, end)
    return {
        "runtime_errors": runtime,
        "order_send_failures": order_fail,
        "abnormal_stop_distance": abnormal,
    }


def collect_daily_report(config: dict[str, Any], *, day: datetime | None = None) -> dict[str, Any]:
    """Build one UTC-day forward demo report."""
    start_dt = _utc_day(day)
    end_dt = start_dt + timedelta(days=1)
    setups, meta_acc, meta_rej = _count_meta_decisions(start_dt)

    day_trades = []
    for t in _completed_trades(since_start=True):
        exit_ts = (t.get("exit") or {}).get("timestamp", "")
        t_parsed = _parse_ts(str(exit_ts))
        if t_parsed and start_dt <= t_parsed < end_dt:
            day_trades.append(t)

    pnls = [float((t.get("exit") or {}).get("pnl_usd", 0)) for t in day_trades]
    rs = [float((t.get("exit") or {}).get("pnl_R", 0)) for t in day_trades]
    wins = sum(1 for r in rs if r > 0)
    trade_dicts = [{"pnl": p} for p in pnls]
    pf = _profit_factor(trade_dicts) if pnls else 0.0

    all_trades = _completed_trades(since_start=True)
    all_pnls = [float((t.get("exit") or {}).get("pnl_usd", 0)) for t in all_trades]
    all_rs = [float((t.get("exit") or {}).get("pnl_R", 0)) for t in all_trades]
    cum_pf = _profit_factor([{"pnl": p} for p in all_pnls]) if all_pnls else 0.0

    equity = 200.0
    try:
        import MetaTrader5 as mt5
        from tradingbot.adapters.mt5_utils import attach_mt5_session

        if attach_mt5_session(config, strict_account=False, use_lock=False, timeout_ms=8000):
            acc = mt5.account_info()
            if acc:
                equity = float(acc.balance) - sum(pnls)
    except Exception:
        pass

    peak = equity
    cur = equity
    max_dd = 0.0
    for p in sorted(day_trades, key=lambda x: (x.get("exit") or {}).get("timestamp", "")):
        cur += float((p.get("exit") or {}).get("pnl_usd", 0))
        peak = max(peak, cur)
        if peak > 0:
            max_dd = max(max_dd, (peak - cur) / peak * 100.0)

    quality = _quality_flags(start_dt)
    return {
        "date": start_dt.strftime("%Y-%m-%d"),
        "total_setups": setups,
        "meta_rejected": meta_rej,
        "meta_accepted": meta_acc,
        "executed_trades": len(day_trades),
        "win_rate_pct": round(wins / len(rs) * 100, 2) if rs else 0.0,
        "profit_factor": round(float(pf), 3) if pf not in ("inf", float("inf")) else "inf",
        "expectancy_R": round(sum(rs) / len(rs), 3) if rs else 0.0,
        "max_intraday_dd_percent": round(max_dd, 4),
        "cumulative_pf": round(float(cum_pf), 3) if cum_pf not in ("inf", float("inf")) else "inf",
        "cumulative_expectancy_R": round(sum(all_rs) / len(all_rs), 3) if all_rs else 0.0,
        "quality": quality,
    }


def save_daily_report(report: dict[str, Any]) -> Path:
    PHASE51A_DIR.mkdir(parents=True, exist_ok=True)
    out = PHASE51A_DIR / f"daily_{report['date']}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out


def rollup_certification(
    config: dict[str, Any],
    *,
    days: int = TARGET_DAYS,
    start_date: str | None = None,
) -> dict[str, Any]:
    start_str = start_date or forward_start_date() or ensure_forward_start()
    start = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    today = _utc_day()

    daily_reports: list[dict[str, Any]] = []
    forward_days = 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day > today:
            break
        report = collect_daily_report(config, day=day)
        save_daily_report(report)
        daily_reports.append(report)
        forward_days += 1

    trades = _completed_trades(since_start=True)
    executed = len(trades)
    pnls = [float((t.get("exit") or {}).get("pnl_usd", 0)) for t in trades]
    rs = [float((t.get("exit") or {}).get("pnl_R", 0)) for t in trades]
    cum_pf = _profit_factor([{"pnl": p} for p in pnls]) if pnls else 0.0
    cum_exp = sum(rs) / len(rs) if rs else 0.0

    equity = 200.0
    peak = equity
    cur = equity
    max_dd_pct = 0.0
    for t in sorted(trades, key=lambda x: (x.get("exit") or {}).get("timestamp", "")):
        cur += float((t.get("exit") or {}).get("pnl_usd", 0))
        peak = max(peak, cur)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - cur) / peak * 100.0)

    runtime_errors = sum(d["quality"]["runtime_errors"] for d in daily_reports)
    order_fails = sum(d["quality"]["order_send_failures"] for d in daily_reports)
    abnormal = sum(d["quality"]["abnormal_stop_distance"] for d in daily_reports)
    any_runtime_error = runtime_errors > 0 or order_fails > 0 or abnormal > 0

    pf_num = float(cum_pf) if cum_pf not in ("inf", float("inf")) else 999.0
    window_complete = forward_days >= days and (today - start).days >= days - 1

    certified = (
        window_complete
        and executed >= MIN_SAMPLE
        and pf_num > PF_GATE
        and cum_exp > EXP_R_GATE
        and max_dd_pct < MAX_DD_GATE
        and not any_runtime_error
    )

    return {
        "start_date": start_str,
        "forward_days": forward_days,
        "target_days": days,
        "window_complete": window_complete,
        "executed_trades": executed,
        "cumulative_pf": cum_pf,
        "cumulative_expectancy_R": round(cum_exp, 3),
        "max_drawdown_percent": round(max_dd_pct, 4),
        "runtime_errors": runtime_errors,
        "order_send_failures": order_fails,
        "abnormal_stop_distance": abnormal,
        "any_runtime_error": any_runtime_error,
        "certified_for_real": certified,
        "daily_reports": daily_reports,
    }


def write_result(report: dict[str, Any]) -> Path:
    lines = [
        "PHASE_51A_RESULT",
        f"FORWARD_DAYS={report.get('forward_days', 0)}",
        f"EXECUTED_TRADES={report.get('executed_trades', 0)}",
        f"CUMULATIVE_PF={report.get('cumulative_pf', 0)}",
        f"CUMULATIVE_EXPECTANCY_R={report.get('cumulative_expectancy_R', 0)}",
        f"MAX_DD_PERCENT={report.get('max_drawdown_percent', 0)}",
        f"ANY_RUNTIME_ERROR={'YES' if report.get('any_runtime_error') else 'NO'}",
        f"CERTIFIED_FOR_REAL={'YES' if report.get('certified_for_real') else 'NO'}",
    ]
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return RESULT_PATH


def run_daily_rollup(config: dict[str, Any]) -> dict[str, Any]:
    if not is_phase51a_enabled():
        return {}
    ensure_forward_start()
    report = collect_daily_report(config)
    save_daily_report(report)
    cert = rollup_certification(config)
    write_result(cert)
    return cert
