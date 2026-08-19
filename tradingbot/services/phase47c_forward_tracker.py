"""Phase 47C — 5-day forward demo validation metrics (daily snapshots + certification)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import _profit_factor

ROOT = Path(__file__).resolve().parents[2]
PHASE47C_DIR = ROOT / "logs" / "phase47c"
EVENTS_PATH = PHASE47C_DIR / "events.jsonl"
START_PATH = PHASE47C_DIR / "forward_start.json"
RESULT_PATH = ROOT / "logs" / "phase47c_forward_result.txt"

_MAGIC = 234000


def is_phase47c_enabled() -> bool:
    return os.getenv("PHASE47C_FORWARD_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def _utc_day(day: datetime | None = None) -> datetime:
    d = day or datetime.now(timezone.utc)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _day_bounds(day: datetime) -> tuple[str, str, datetime, datetime]:
    start = _utc_day(day)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat(), start, end


def _read_jsonl(path: Path, *, tail_lines: int | None = None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    if tail_lines is not None and tail_lines > 0:
        try:
            with path.open("rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                chunk = min(size, max(tail_lines * 256, 65536))
                fh.seek(max(0, size - chunk))
                raw = fh.read().decode("utf-8", errors="replace")
            lines = raw.splitlines()[-tail_lines:]
        except Exception:
            lines = path.read_text(encoding="utf-8").splitlines()[-tail_lines:]
    else:
        lines = path.read_text(encoding="utf-8").splitlines()

    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _in_day(ts_raw: str, start: datetime, end: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
    except Exception:
        return False
    return start <= ts < end


def log_phase47c_event(event: str, **fields: Any) -> None:
    """Append structured Phase 47C event (position mgmt, approvals, exits)."""
    if not is_phase47c_enabled():
        return
    PHASE47C_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    with EVENTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_forward_start(*, force: bool = False) -> str:
    """Record UTC start date for the 5-day forward window."""
    PHASE47C_DIR.mkdir(parents=True, exist_ok=True)
    today = _utc_day().strftime("%Y-%m-%d")
    if START_PATH.is_file() and not force:
        try:
            data = json.loads(START_PATH.read_text(encoding="utf-8"))
            return str(data.get("start_date") or today)
        except Exception:
            pass
    START_PATH.write_text(
        json.dumps({"start_date": today, "recorded_at": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )
    return today


def forward_start_datetime() -> datetime | None:
    if not START_PATH.is_file():
        return None
    try:
        data = json.loads(START_PATH.read_text(encoding="utf-8"))
        day = str(data.get("start_date") or "")
        recorded = str(data.get("recorded_at") or "")
        if recorded:
            ts = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)
        if day:
            return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def _after_forward_start(ts_raw: str) -> bool:
    start = forward_start_datetime()
    if start is None:
        return True
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
    except Exception:
        return False
    return ts >= start


def forward_start_date() -> str | None:
    if not START_PATH.is_file():
        return None
    try:
        return str(json.loads(START_PATH.read_text(encoding="utf-8")).get("start_date") or "")
    except Exception:
        return None


def _count_router_pa_setups(start: datetime, end: datetime) -> int:
    path = ROOT / "logs" / "router_decisions.jsonl"
    count = 0
    for row in _read_jsonl(path, tail_lines=200_000):
        ts = row.get("logged_at") or row.get("timestamp") or ""
        if not _in_day(ts, start, end) or not _after_forward_start(str(ts)):
            continue
        if str(row.get("pa_signal", "")).upper() in ("BUY", "SELL"):
            count += 1
    return count


def _count_meta_decisions(start: datetime, end: datetime) -> tuple[int, int]:
    path = ROOT / "data" / "meta_decisions.jsonl"
    accepted = rejected = 0
    for row in _read_jsonl(path, tail_lines=50_000):
        if row.get("event") == "trade_closed":
            continue
        if "allowed" not in row:
            continue
        if not _in_day(str(row.get("ts", "")), start, end) or not _after_forward_start(str(row.get("ts", ""))):
            continue
        if row.get("allowed"):
            accepted += 1
        else:
            rejected += 1
    return accepted, rejected


def _count_riskgate_rejections(start: datetime, end: datetime) -> int:
    path = ROOT / "logs" / "rejection_events.jsonl"
    count = 0
    for row in _read_jsonl(path, tail_lines=100_000):
        if not _in_day(str(row.get("ts", "")), start, end) or not _after_forward_start(str(row.get("ts", ""))):
            continue
        stage = str(row.get("stage", "")).upper()
        reason = str(row.get("reason", ""))
        lower = reason.lower()
        if stage != "RISKGATE":
            continue
        if "meta-labeler rejected" in lower:
            continue
        if "micro_stop_compressed" in lower or "micro_feasible_execution" in lower:
            continue
        count += 1
    return count


def _count_phase47c_events(start: datetime, end: datetime, event: str) -> int:
    count = 0
    for row in _read_jsonl(EVENTS_PATH):
        if row.get("event") != event:
            continue
        if not _in_day(str(row.get("ts", "")), start, end):
            continue
        count += 1
    return count


def _journal_executions(start_iso: str, end_iso: str, base_dir: Path) -> dict[str, Any]:
    path = base_dir / "data" / "trade_journal.db"
    out = {"total": 0, "ok": 0, "failed": 0}
    if not path.is_file():
        return out
    with sqlite3.connect(path) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT success, ts FROM executions WHERE ts >= ? AND ts < ?",
            (start_iso, end_iso),
        )
        for success, ts in cur.fetchall():
            if not _after_forward_start(str(ts)):
                continue
            out["total"] += 1
            if success:
                out["ok"] += 1
            else:
                out["failed"] += 1
    return out


def _classify_exit_reason(deal: Any) -> str:
    try:
        import MetaTrader5 as mt5

        reason = int(getattr(deal, "reason", -1))
        if reason == getattr(mt5, "DEAL_REASON_SL", 4):
            return "sl_hit"
        if reason == getattr(mt5, "DEAL_REASON_TP", 5):
            return "tp_hit"
    except Exception:
        pass
    comment = str(getattr(deal, "comment", "") or "").lower()
    if "sl" in comment and "trail" not in comment:
        return "sl_hit"
    if "tp" in comment:
        return "tp_hit"
    return "other"


def _mt5_closed_trades(config: dict[str, Any], start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Closed bot exit deals with PnL and R-multiple."""
    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.mt5_utils import attach_mt5_session
        from tradingbot.domain.position_logic import contract_size
        from tradingbot.services.trade_journal import TradeJournal
    except ImportError:
        return []

    if not attach_mt5_session(config, strict_account=False, use_lock=False, timeout_ms=8000):
        return []

    deals = mt5.history_deals_get(start, end)
    if not deals:
        return []

    base_dir = config.get("BASE_DIR", str(ROOT))
    journal = TradeJournal(base_dir)
    closed: list[dict[str, Any]] = []

    for deal in sorted(deals, key=lambda d: int(getattr(d, "time", 0))):
        if int(getattr(deal, "entry", 0)) != 1:
            continue
        if int(getattr(deal, "magic", 0) or 0) != _MAGIC:
            continue
        profit = float(getattr(deal, "profit", 0.0))
        volume = float(getattr(deal, "volume", 0.01))
        symbol = str(getattr(deal, "symbol", "XAUUSD"))
        position_id = int(getattr(deal, "position_id", 0) or getattr(deal, "order", 0))
        ts = datetime.fromtimestamp(int(deal.time), tz=timezone.utc).isoformat()
        exit_kind = _classify_exit_reason(deal)

        entry_price = sl = None
        direction = "BUY"
        try:
            with journal._connect() as conn:
                row = conn.execute(
                    """
                    SELECT fill_price, sl, direction FROM executions
                    WHERE (ticket=? OR ticket=?) AND success=1
                    ORDER BY id DESC LIMIT 1
                    """,
                    (position_id, abs(position_id)),
                ).fetchone()
                if row:
                    entry_price = float(row["fill_price"]) if row["fill_price"] else None
                    sl = float(row["sl"]) if row["sl"] else None
                    direction = str(row["direction"] or "BUY")
        except Exception:
            pass

        pnl_r = 0.0
        if entry_price and sl and volume > 0:
            risk = abs(entry_price - sl) * contract_size(symbol) * volume
            if risk > 0:
                pnl_r = round(profit / risk, 4)

        if not _after_forward_start(ts):
            continue

        closed.append(
            {
                "ts": ts,
                "ticket": position_id or int(getattr(deal, "ticket", 0)),
                "symbol": symbol,
                "profit": round(profit, 2),
                "pnl_r": pnl_r,
                "exit_kind": exit_kind,
                "comment": str(getattr(deal, "comment", "") or ""),
            }
        )
    return closed


def _count_abnormal_stops(start: datetime, end: datetime) -> int:
    path = ROOT / "logs" / "rejection_events.jsonl"
    count = 0
    for row in _read_jsonl(path, tail_lines=100_000):
        if not _in_day(str(row.get("ts", "")), start, end) or not _after_forward_start(str(row.get("ts", ""))):
            continue
        reason = str(row.get("reason", "")).upper()
        if "ABNORMAL_STOP_DISTANCE" in reason or "MICRO_STOP_TOO_WIDE" in reason:
            count += 1
    return count


def _intraday_drawdown_pct(closed_trades: list[dict[str, Any]], day_start_equity: float) -> float:
    if day_start_equity <= 0:
        return 0.0
    equity = day_start_equity
    peak = equity
    max_dd = 0.0
    for t in sorted(closed_trades, key=lambda x: x.get("ts", "")):
        equity += float(t.get("profit", 0.0))
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak * 100.0
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)


def collect_daily_metrics(
    config: dict[str, Any],
    *,
    day: datetime | None = None,
    cumulative_closed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one UTC-day metrics snapshot from live logs + MT5."""
    start_iso, end_iso, start_dt, end_dt = _day_bounds(day or datetime.now(timezone.utc))
    base_dir = Path(config.get("BASE_DIR", str(ROOT)))

    meta_accepted, meta_rejected = _count_meta_decisions(start_dt, end_dt)
    riskgate_rejected = _count_riskgate_rejections(start_dt, end_dt)
    riskgate_approved = _count_phase47c_events(start_dt, end_dt, "riskgate_approved")
    executions = _journal_executions(start_iso, end_iso, base_dir)

    closed_today = _mt5_closed_trades(config, start_dt, end_dt)
    sl_hits = sum(1 for t in closed_today if t.get("exit_kind") == "sl_hit")
    tp_hits = sum(1 for t in closed_today if t.get("exit_kind") == "tp_hit")
    partial_hits = _count_phase47c_events(start_dt, end_dt, "partial_hit")
    trailing_hits = _count_phase47c_events(start_dt, end_dt, "trailing_hit")

    daily_pnl_usd = round(sum(float(t.get("profit", 0.0)) for t in closed_today), 2)
    daily_pnl_r = round(sum(float(t.get("pnl_r", 0.0)) for t in closed_today), 4)

    day_start_equity = 200.0
    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.mt5_utils import attach_mt5_session

        if attach_mt5_session(config, strict_account=False, use_lock=False, timeout_ms=8000):
            acc = mt5.account_info()
            if acc is not None:
                day_start_equity = float(acc.balance) - daily_pnl_usd
    except Exception:
        pass

    max_intraday_dd = _intraday_drawdown_pct(closed_today, day_start_equity)

    all_closed = list(cumulative_closed or []) + closed_today
    trade_dicts = [{"pnl": t["profit"]} for t in all_closed]
    pf = _profit_factor(trade_dicts)
    r_vals = [float(t.get("pnl_r", 0.0)) for t in all_closed if t.get("pnl_r") is not None]
    cum_expectancy_r = round(sum(r_vals) / len(r_vals), 4) if r_vals else 0.0

    abnormal_stops = _count_abnormal_stops(start_dt, end_dt)
    runtime_errors = _count_phase47c_events(start_dt, end_dt, "runtime_error")

    return {
        "date": start_dt.strftime("%Y-%m-%d"),
        "signal_layer": {
            "raw_pa_setups": _count_router_pa_setups(start_dt, end_dt),
            "meta_rejected": meta_rejected,
            "meta_accepted": meta_accepted,
        },
        "risk_layer": {
            "riskgate_rejected": riskgate_rejected,
            "riskgate_approved": riskgate_approved,
        },
        "execution_layer": {
            "executed_trades": executions["ok"],
            "sl_hits": sl_hits,
            "tp_hits": tp_hits,
            "partial_hits": partial_hits,
            "trailing_hits": trailing_hits,
        },
        "performance": {
            "daily_pnl_usd": daily_pnl_usd,
            "daily_pnl_R": daily_pnl_r,
            "max_intraday_drawdown_pct": max_intraday_dd,
            "cumulative_pf": pf,
            "cumulative_expectancy_R": cum_expectancy_r,
        },
        "quality": {
            "execution_errors": executions["failed"],
            "abnormal_stop_distance": abnormal_stops,
            "runtime_errors": runtime_errors,
        },
        "_closed_trades": closed_today,
    }


def save_daily_snapshot(metrics: dict[str, Any]) -> Path:
    PHASE47C_DIR.mkdir(parents=True, exist_ok=True)
    day = metrics["date"]
    out = PHASE47C_DIR / f"daily_{day}.json"
    payload = {k: v for k, v in metrics.items() if not k.startswith("_")}
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def rollup_forward_period(
    config: dict[str, Any],
    *,
    days: int = 5,
    start_date: str | None = None,
) -> dict[str, Any]:
    """Aggregate daily snapshots across the forward window and certify."""
    start_str = start_date or forward_start_date() or ensure_forward_start()
    start = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    today = _utc_day()

    daily_snapshots: list[dict[str, Any]] = []
    cumulative_closed: list[dict[str, Any]] = []
    forward_days = 0

    for offset in range(days):
        day = start + timedelta(days=offset)
        if day > today:
            break
        metrics = collect_daily_metrics(config, day=day, cumulative_closed=cumulative_closed)
        cumulative_closed.extend(metrics.pop("_closed_trades", []))
        save_daily_snapshot(metrics)
        daily_snapshots.append(metrics)
        forward_days += 1

    executed = sum(d["execution_layer"]["executed_trades"] for d in daily_snapshots)
    wins = sum(1 for t in cumulative_closed if float(t.get("profit", 0)) > 0)
    win_rate = round(wins / len(cumulative_closed) * 100, 2) if cumulative_closed else 0.0

    trade_dicts = [{"pnl": t["profit"]} for t in cumulative_closed]
    cum_pf = _profit_factor(trade_dicts)
    r_vals = [float(t.get("pnl_r", 0.0)) for t in cumulative_closed]
    cum_exp_r = round(sum(r_vals) / len(r_vals), 4) if r_vals else 0.0

    max_dd_pct = 0.0
    if cumulative_closed:
        equity = 200.0
        peak = equity
        for t in sorted(cumulative_closed, key=lambda x: x.get("ts", "")):
            equity += float(t.get("profit", 0.0))
            peak = max(peak, equity)
            if peak > 0:
                max_dd_pct = max(max_dd_pct, (peak - equity) / peak * 100.0)
    max_dd_pct = round(max_dd_pct, 4)

    exec_errors = sum(d["quality"]["execution_errors"] for d in daily_snapshots)
    abnormal_stops = sum(d["quality"]["abnormal_stop_distance"] for d in daily_snapshots)
    runtime_errors = sum(d["quality"]["runtime_errors"] for d in daily_snapshots)
    any_runtime_error = exec_errors > 0 or runtime_errors > 0 or abnormal_stops > 0

    pf_num = float(cum_pf) if cum_pf not in ("inf", "INF") else 999.0
    window_complete = forward_days >= days and (today - start).days >= days - 1

    certified = (
        window_complete
        and executed >= 3
        and pf_num > 1.2
        and cum_exp_r > 0
        and max_dd_pct < 3.0
        and exec_errors == 0
        and abnormal_stops == 0
        and runtime_errors == 0
    )

    return {
        "start_date": start_str,
        "forward_days": forward_days,
        "target_days": days,
        "window_complete": window_complete,
        "daily_snapshots": daily_snapshots,
        "executed_trades": executed,
        "closed_trades": len(cumulative_closed),
        "win_rate": win_rate,
        "cumulative_pf": cum_pf,
        "cumulative_expectancy_R": cum_exp_r,
        "max_drawdown_percent": max_dd_pct,
        "execution_errors": exec_errors,
        "abnormal_stop_distance": abnormal_stops,
        "runtime_errors": runtime_errors,
        "any_runtime_error": any_runtime_error,
        "certified_for_real": certified,
    }


def write_phase47c_result(report: dict[str, Any]) -> Path:
    lines = [
        "PHASE_47C_RESULT",
        f"FORWARD_DAYS={report.get('forward_days', 0)}",
        f"EXECUTED_TRADES={report.get('executed_trades', 0)}",
        f"WIN_RATE={report.get('win_rate', 0)}",
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
    """Collect today + refresh 5-day certification (called from LiveOps)."""
    if not is_phase47c_enabled():
        return {}
    ensure_forward_start()
    today_metrics = collect_daily_metrics(config)
    save_daily_snapshot(today_metrics)
    report = rollup_forward_period(config)
    write_phase47c_result(report)
    return report
