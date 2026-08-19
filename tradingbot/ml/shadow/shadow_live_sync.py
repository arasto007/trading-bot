"""Sync MT5 closed deals into shadow outcome log (live trades)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.integration.config import is_ml_shadow_enabled
from tradingbot.ml.shadow.shadow_logger import record_shadow_outcome, record_shadow_trade_record
from tradingbot.services.trade_journal import TradeJournal

logger = logging.getLogger(__name__)

_STATE = Path(__file__).resolve().parents[3] / "data" / "ml_shadow_deals_seen.json"


def _load_seen() -> set[int]:
    if not _STATE.is_file():
        return set()
    try:
        data = json.loads(_STATE.read_text(encoding="utf-8"))
        return {int(x) for x in data.get("deal_tickets", [])}
    except Exception:
        return set()


def _save_seen(seen: set[int]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    trimmed = sorted(seen)[-5000:]
    _STATE.write_text(
        json.dumps({"deal_tickets": trimmed}, indent=2),
        encoding="utf-8",
    )


def _lookup_entry_meta(
    journal: TradeJournal,
    *,
    position_id: int,
    symbol: str,
) -> tuple[float | None, float | None, str, str | None]:
    """Entry price, SL, direction, entry_ts from journal."""
    try:
        with journal._connect() as conn:
            row = conn.execute(
                """
                SELECT fill_price, sl, direction, lot, ts
                FROM executions
                WHERE (ticket=? OR ticket=?) AND success=1
                ORDER BY id DESC LIMIT 1
                """,
                (position_id, abs(position_id)),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT fill_price, sl, direction, lot, ts
                    FROM executions
                    WHERE symbol=? AND success=1
                    ORDER BY id DESC LIMIT 1
                    """,
                    (symbol,),
                ).fetchone()
            if row is None:
                return None, None, "BUY", None
            return (
                float(row["fill_price"]) if row["fill_price"] else None,
                float(row["sl"]) if row["sl"] else None,
                str(row["direction"] or "BUY"),
                str(row["ts"]) if row["ts"] else None,
            )
    except Exception:
        return None, None, "BUY", None


def _lookup_entry_sl(
    journal: TradeJournal,
    *,
    position_id: int,
    symbol: str,
) -> tuple[float | None, float, str]:
    entry, sl, direction, _ = _lookup_entry_meta(journal, position_id=position_id, symbol=symbol)
    return entry, sl or 0.01, direction


def _resolve_shadow_fields(
    *,
    ticket: int,
    direction: str,
    close_ts: str,
    base_dir: str,
) -> tuple[str, str, float | None, str]:
    from tradingbot.ml.shadow.phase49a_metrics import load_shadow_events, shadow_log_path, _index_entries, _index_cycles, _match_cycle
    from tradingbot.ml.shadow.shadow_observer import extract_ml_fields

    events = load_shadow_events(shadow_log_path(base_dir))
    entries = _index_entries(events)
    entry = entries.get(int(ticket))
    if entry:
        return (
            str(entry.get("live_engine_direction", direction)).upper(),
            str(entry.get("ml_prediction_direction", "HOLD")).upper(),
            entry.get("ml_probability"),
            str(entry.get("live_engine", "")),
        )
    cycles = _index_cycles(events)
    cyc = _match_cycle(cycles, before_ts=close_ts, live_direction=direction)
    if cyc:
        ml_dir, ml_prob = extract_ml_fields(cyc)
        return (
            str(cyc.get("live_signal", direction)).upper(),
            ml_dir,
            ml_prob,
            str(cyc.get("live_engine", "")),
        )
    return direction.upper(), "HOLD", None, ""


def _pnl_r(
    *,
    profit: float,
    entry: float | None,
    sl: float | None,
    lot: float,
    symbol: str,
    is_buy: bool,
) -> float:
    if entry is None or sl is None or lot <= 0:
        return 0.0
    risk = abs(entry - sl) * contract_size(symbol) * lot
    if risk <= 0:
        return 0.0
    return round(profit / risk, 4)


def sync_mt5_closed_deals(config: dict[str, Any] | None = None) -> int:
    """Record new MT5 exit deals as shadow_outcome events. Returns count added."""
    if not is_ml_shadow_enabled():
        return 0
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return 0

    cfg = dict(config or {})
    base_dir = cfg.get("BASE_DIR", str(Path(__file__).resolve().parents[3]))
    journal = TradeJournal(base_dir)
    seen = _load_seen()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=14)
    deals = mt5.history_deals_get(start, now)
    if deals is None:
        return 0

    added = 0
    for deal in sorted(deals, key=lambda d: d.time):
        ticket = int(getattr(deal, "ticket", 0))
        if ticket in seen:
            continue
        if int(getattr(deal, "entry", 0)) != 1:
            continue
        magic = int(getattr(deal, "magic", 0))
        if magic <= 0:
            continue

        seen.add(ticket)
        symbol = str(getattr(deal, "symbol", "XAUUSD"))
        profit = float(getattr(deal, "profit", 0.0))
        volume = float(getattr(deal, "volume", 0.01))
        position_id = int(getattr(deal, "position_id", 0) or getattr(deal, "order", 0))
        deal_type = int(getattr(deal, "type", 0))
        is_buy = deal_type == 1  # exit sell deal => long was closed
        direction = "BUY" if is_buy else "SELL"
        ts = datetime.fromtimestamp(int(deal.time), tz=timezone.utc).isoformat()

        entry, sl, _ = _lookup_entry_sl(journal, position_id=position_id, symbol=symbol)
        pnl_r = _pnl_r(
            profit=profit,
            entry=entry,
            sl=sl,
            lot=volume,
            symbol=symbol,
            is_buy=is_buy,
        )
        record_shadow_outcome(
            timestamp=ts,
            ticket=position_id or ticket,
            direction=direction,
            pnl_r=pnl_r,
            pnl=profit,
            exit_reason=str(getattr(deal, "comment", "") or "mt5_close"),
            engine="live_mt5",
        )
        live_dir, ml_dir, ml_prob, live_engine = _resolve_shadow_fields(
            ticket=int(position_id or ticket),
            direction=direction,
            close_ts=ts,
            base_dir=base_dir,
        )
        record_shadow_trade_record(
            timestamp=ts,
            ticket=position_id or ticket,
            live_engine_direction=live_dir,
            ml_prediction_direction=ml_dir,
            ml_probability=ml_prob,
            pnl=profit,
            pnl_r=pnl_r,
            exit_reason=str(getattr(deal, "comment", "") or "mt5_close"),
            live_engine=live_engine,
        )
        try:
            from tradingbot.services.phase51a_forward_cert import is_phase51a_enabled, log_trade_exit

            if is_phase51a_enabled():
                log_trade_exit(
                    ticket=int(position_id or ticket),
                    exit_reason=str(getattr(deal, "comment", "") or "mt5_close"),
                    pnl_usd=profit,
                    pnl_r=pnl_r,
                    exit_ts=ts,
                )
        except Exception:
            pass
        try:
            from tradingbot.services.engine_telemetry import get_engine_telemetry, resolve_engine_name

            get_engine_telemetry(base_dir).record_trade_close(
                resolve_engine_name(live_engine or "PA"),
                ticket=int(position_id or ticket),
                symbol=symbol.replace("_i", ""),
                direction=direction,
                pnl_usd=profit,
                pnl_r=pnl_r,
                exit_reason=str(getattr(deal, "comment", "") or "mt5_close"),
            )
        except Exception:
            pass
        try:
            from tradingbot.services.meta_decision_log import log_trade_outcome
            from tradingbot.services.phase47c_forward_tracker import is_phase47c_enabled, log_phase47c_event

            if is_phase47c_enabled():
                log_trade_outcome(
                    symbol=symbol.replace("_i", ""),
                    timeframe="M5",
                    ticket=position_id or ticket,
                    pnl=profit,
                    r_multiple=pnl_r,
                )
                log_phase47c_event(
                    "trade_closed",
                    ticket=position_id or ticket,
                    profit=profit,
                    pnl_r=pnl_r,
                    direction=direction,
                )
        except Exception:
            pass
        added += 1

    _save_seen(seen)
    if added:
        logger.info("Shadow live sync: recorded %s MT5 closed deals", added)
    return added
