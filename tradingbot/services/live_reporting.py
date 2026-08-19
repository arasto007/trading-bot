"""Daily P/L, slippage summary, and journal vs MT5 reconciliation."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utc_day_bounds(day: datetime | None = None) -> tuple[str, str]:
    d = day or datetime.now(timezone.utc)
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def current_spread_pips(config: dict[str, Any]) -> float | None:
    """Live bid/ask spread in pips for primary symbol."""
    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.mt5_utils import attach_mt5_session, is_mt5_lock_held_by_other
        from tradingbot.adapters.symbols import resolve_broker_symbol
        from tradingbot.config.live import PRIMARY_SYMBOL
        from tradingbot.domain.session_logic import spread_pips_from_prices

        if is_mt5_lock_held_by_other():
            return None

        symbol = (config.get("SYMBOLS") or [PRIMARY_SYMBOL])[0]
        broker = resolve_broker_symbol(symbol, config)
        if not attach_mt5_session(config, strict_account=False, use_lock=False):
            return None
        tick = mt5.symbol_info_tick(broker)
        if tick is None:
            return None
        return round(
            spread_pips_from_prices(float(tick.ask), float(tick.bid), symbol),
            3,
        )
    except Exception:
        return None


def journal_summary(base_dir: str | Path, *, day: datetime | None = None) -> dict[str, Any]:
    path = Path(base_dir) / "data" / "trade_journal.db"
    start, end = _utc_day_bounds(day)
    out: dict[str, Any] = {
        "window_start": start,
        "window_end": end,
        "executions_total": 0,
        "executions_ok": 0,
        "slippage_avg_pips": None,
        "slippage_max_pips": None,
        "modes": {},
    }
    if not path.is_file():
        return out

    with sqlite3.connect(path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT mode, success, slippage_pips, ticket
            FROM executions
            WHERE ts >= ? AND ts < ?
            """,
            (start, end),
        )
        rows = cur.fetchall()
        slips: list[float] = []
        for mode, success, slip, ticket in rows:
            out["executions_total"] += 1
            if success:
                out["executions_ok"] += 1
            out["modes"][mode] = out["modes"].get(mode, 0) + 1
            if slip is not None:
                slips.append(float(slip))
        if slips:
            out["slippage_avg_pips"] = round(sum(slips) / len(slips), 3)
            out["slippage_max_pips"] = round(max(slips), 3)

        cur.execute(
            """
            SELECT COUNT(*) FROM cycle_events
            WHERE ts >= ? AND ts < ? AND state = 'idle' AND detail LIKE '%no_signal%'
            """,
            (start, end),
        )
        out["idle_no_signal_cycles"] = int(cur.fetchone()[0] or 0)

    return out


def mt5_deals_summary(config: dict[str, Any], *, day: datetime | None = None) -> dict[str, Any]:
    start_dt = (day or datetime.now(timezone.utc)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end_dt = start_dt + timedelta(days=1)
    out: dict[str, Any] = {
        "deals_count": 0,
        "profit": 0.0,
        "balance": None,
        "equity": None,
        "login": None,
        "server": None,
    }
    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.mt5_utils import attach_mt5_session

        if not attach_mt5_session(config, strict_account=False, use_lock=False):
            out["error"] = "mt5_not_connected"
            return out

        acc = mt5.account_info()
        if acc:
            out["balance"] = round(float(acc.balance), 2)
            out["equity"] = round(float(acc.equity), 2)
            out["login"] = int(acc.login)
            out["server"] = str(acc.server)

        deals = mt5.history_deals_get(start_dt, end_dt)
        if deals:
            bot_deals = [d for d in deals if int(getattr(d, "magic", 0) or 0) == 234000]
            out["deals_count"] = len(bot_deals)
            out["profit"] = round(sum(float(d.profit) for d in bot_deals), 2)
    except Exception as exc:
        out["error"] = str(exc)
    return out


def reconcile_journal_mt5(base_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    """Compare today's journal tickets vs MT5 deals (magic 234000)."""
    path = Path(base_dir) / "data" / "trade_journal.db"
    start, end = _utc_day_bounds()
    journal_tickets: set[int] = set()
    if path.is_file():
        with sqlite3.connect(path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ticket FROM executions
                WHERE ts >= ? AND ts < ? AND success = 1 AND ticket IS NOT NULL
                """,
                (start, end),
            )
            for (ticket,) in cur.fetchall():
                if ticket:
                    journal_tickets.add(int(ticket))

    mt5_tickets: set[int] = set()
    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.mt5_utils import attach_mt5_session

        if attach_mt5_session(config, strict_account=False, use_lock=False):
            start_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            deals = mt5.history_deals_get(start_dt, start_dt + timedelta(days=1))
            if deals:
                for d in deals:
                    if int(getattr(d, "magic", 0) or 0) == 234000 and int(d.entry) == 0:
                        mt5_tickets.add(int(d.order))
    except Exception as exc:
        return {"ok": False, "error": str(exc), "journal_only": [], "mt5_only": []}

    journal_only = sorted(journal_tickets - mt5_tickets)
    mt5_only = sorted(mt5_tickets - journal_tickets)
    return {
        "ok": not journal_only and not mt5_only,
        "journal_tickets": len(journal_tickets),
        "mt5_tickets": len(mt5_tickets),
        "journal_only": journal_only[:20],
        "mt5_only": mt5_only[:20],
    }


def build_daily_report(base_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    journal = journal_summary(base_dir, day=now)
    report = {
        "generated_at": now.isoformat(),
        "phase": "phase4_live_proof",
        "journal": journal,
        "spread_pips": current_spread_pips(config),
        "mt5": mt5_deals_summary(config, day=now),
        "reconcile": reconcile_journal_mt5(base_dir, config),
    }
    out_path = Path(base_dir) / "logs" / "daily_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_daily_report_telegram(report: dict[str, Any]) -> str:
    j = report.get("journal", {})
    m = report.get("mt5", {})
    r = report.get("reconcile", {})
    spread = report.get("spread_pips")
    lines = [
        "TradingBot daily report",
        f"Executions: {j.get('executions_ok', 0)}/{j.get('executions_total', 0)} ok",
        f"Slippage avg: {j.get('slippage_avg_pips', '-')} pips (max {j.get('slippage_max_pips', '-')})",
        f"Spread now: {spread if spread is not None else '-'} pips",
        f"MT5 bot deals: {m.get('deals_count', 0)} profit={m.get('profit', 0)}",
        f"Balance: {m.get('balance', '-')} Equity: {m.get('equity', '-')}",
        f"Reconcile OK: {r.get('ok', False)}",
        f"No-signal cycles: {j.get('idle_no_signal_cycles', 0)}",
    ]
    if r.get("journal_only"):
        lines.append(f"Journal-only tickets: {r['journal_only'][:5]}")
    if r.get("mt5_only"):
        lines.append(f"MT5-only tickets: {r['mt5_only'][:5]}")
    return "\n".join(lines)
