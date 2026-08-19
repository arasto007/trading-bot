"""Record paper trade entries and completions into TradeJournal."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.accounting.engine import AccountingEngine
from tradingbot.domain.models import TradingSignal
from tradingbot.services.execution_mode import mode_label
from tradingbot.services.exit_mode import resolve_exit_mode
from tradingbot.services.paper_fill_resolver import resolve_paper_fill
from tradingbot.services.paper_trade_exit import resolve_paper_trade_exit
from tradingbot.services.trade_journal import PAPER_MAGIC, TradeJournal

logger = logging.getLogger(__name__)


def _decision_fields(signal: TradingSignal) -> dict[str, Any]:
    meta = dict(signal.metadata or {})
    confidence = float(signal.confidence or 0.0)
    probability = meta.get("ml_probability", meta.get("probability", confidence))
    try:
        probability = float(probability)
    except (TypeError, ValueError):
        probability = confidence
    risk = meta.get("risk_percent", meta.get("risk"))
    try:
        risk_percent = float(risk) if risk is not None else 0.5
    except (TypeError, ValueError):
        risk_percent = 0.5
    return {
        "regime": str(meta.get("regime") or "UNKNOWN"),
        "engine": str(meta.get("engine_name") or signal.strategy_name or ""),
        "confidence": confidence,
        "probability": probability,
        "risk_percent": risk_percent,
        "checksum": str(meta.get("unified_checksum") or meta.get("trace_id") or ""),
        "model_checksum": str(meta.get("trace_id") or meta.get("unified_checksum") or ""),
        "filter_profile": str(meta.get("filter_profile") or meta.get("regime") or ""),
    }


class PaperTradeRecorder:
    """Journal infrastructure for paper execution lifecycle."""

    def __init__(
        self,
        base_dir: str | Path = ".",
        config: dict[str, Any] | None = None,
        accounting: AccountingEngine | None = None,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._config = config or {}
        self._journal = TradeJournal(self._base_dir)
        self._accounting = accounting

    @property
    def journal(self) -> TradeJournal:
        return self._journal

    def record_entry(
        self,
        signal: TradingSignal,
        lot: float,
        *,
        mt5_price: float | None = None,
        bar_time: pd.Timestamp | None = None,
    ) -> int | None:
        """
        Open a paper trade row and mirror to legacy executions table.

        Returns paper_trades row id, or None if fill could not be resolved.
        """
        fill_price, spread, source = resolve_paper_fill(
            signal,
            base_dir=self._base_dir,
            config=self._config,
            mt5_price=mt5_price,
            bar_time=bar_time,
        )
        if fill_price <= 0:
            logger.error(
                "PAPER journal rejected: unresolved fill for %s %s",
                signal.symbol,
                signal.direction.name,
            )
            return None

        fields = _decision_fields(signal)
        ts_open = datetime.now(timezone.utc).isoformat()
        if bar_time is not None:
            ts = pd.Timestamp(bar_time)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            ts_open = ts.isoformat()
        else:
            meta_ts = (signal.metadata or {}).get("unified_timestamp")
            if meta_ts:
                ts_open = str(meta_ts)

        sl = float(signal.stop_loss) if signal.stop_loss is not None else None
        tp = float(signal.take_profit) if signal.take_profit is not None else None
        rr = None
        if sl is not None and tp is not None and fill_price > 0:
            risk = abs(fill_price - sl)
            if risk > 0:
                reward = (tp - fill_price) if signal.direction.name == "BUY" else (fill_price - tp)
                rr = round(reward / risk, 4)

        trade_id = self._journal.open_paper_trade(
            ts_open=ts_open,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            direction=signal.direction.name,
            entry_price=fill_price,
            fill_price=fill_price,
            sl=sl,
            tp=tp,
            lot=lot,
            spread=spread,
            commission=0.0,
            swap=0.0,
            magic=PAPER_MAGIC,
            regime=fields["regime"],
            engine=fields["engine"],
            confidence=fields["confidence"],
            probability=fields["probability"],
            risk_percent=fields["risk_percent"],
            rr=rr,
            checksum=fields["checksum"],
            model_checksum=fields["model_checksum"],
            filter_profile=fields["filter_profile"],
            fill_source=source,
        )

        self._journal.log_execution(
            mode=mode_label(),
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            direction=signal.direction.name,
            lot=lot,
            requested_price=fill_price,
            fill_price=fill_price,
            slippage_pips=0.0,
            sl=sl,
            tp=tp,
            ticket=-trade_id,
            success=True,
            message=f"paper — simulated fill ({source})",
        )
        logger.info(
            "PAPER journal entry id=%s %s %s lot=%s @ %s source=%s",
            trade_id,
            signal.symbol,
            signal.direction.name,
            lot,
            fill_price,
            source,
        )
        return trade_id

    def complete_trade(
        self,
        trade_id: int,
        *,
        candles: pd.DataFrame | None = None,
        max_hold_bars: int = 72,
    ) -> dict[str, Any] | None:
        """Close an open paper trade using candle walk-forward."""
        row = self._journal.get_paper_trade(trade_id)
        if row is None or row.get("status") != "open":
            return None

        if candles is None:
            from tradingbot.ml.data.stores.candle_store import CandleStore

            candles = CandleStore(self._base_dir).load(row["symbol"], row["timeframe"])
        if candles is None or candles.empty:
            return None

        is_buy = str(row["direction"]) == "BUY"
        exit_mode = resolve_exit_mode(config=self._config)
        exit_info = resolve_paper_trade_exit(
            candles=candles,
            entry_ts=str(row["time_open"]),
            entry_price=float(row["fill_price"]),
            sl=row.get("sl"),
            tp=row.get("tp"),
            is_buy=is_buy,
            lot=float(row["lot"]),
            symbol=str(row["symbol"]),
            max_hold_bars=max_hold_bars,
            spread=float(row.get("spread") or 0.30),
            exit_mode=exit_mode,
        )
        if exit_info.get("exit_reason") == "no_data":
            return None

        ticket = int(row.get("ticket") or -trade_id)
        self._journal.close_paper_trade(
            trade_id,
            ts_close=str(exit_info["exit_timestamp"]),
            exit_price=float(exit_info["exit_price"]),
            exit_reason=str(exit_info["exit_reason"]),
            pnl=float(exit_info["pnl"]),
            pnl_r=float(exit_info["pnl_r"]),
            duration_bars=int(exit_info["duration_bars"]),
            duration_sec=int(exit_info["duration_sec"]),
            mae=float(exit_info["mae"]),
            mfe=float(exit_info["mfe"]),
            rr=exit_info.get("rr"),
        )
        if self._accounting is not None:
            self._accounting.close_trade(
                exit_info=exit_info,
                entry_timestamp=str(row["time_open"]),
                entry_price=float(row["fill_price"]),
                direction=str(row["direction"]),
                lot=float(row["lot"]),
                sl=row.get("sl"),
                tp=row.get("tp"),
                regime=str(row.get("regime") or ""),
                engine=str(row.get("engine") or ""),
                confidence=float(row.get("confidence") or 0),
                risk_percent=float(row.get("risk_percent") or 0),
                trade_id=str(trade_id),
            )
        try:
            from tradingbot.ml.shadow.shadow_logger import record_shadow_outcome

            record_shadow_outcome(
                timestamp=str(exit_info.get("exit_timestamp") or row["time_open"]),
                ticket=int(row.get("ticket") or -trade_id),
                direction=str(row["direction"]),
                pnl_r=float(exit_info["pnl_r"]),
                pnl=float(exit_info["pnl"]),
                exit_reason=str(exit_info["exit_reason"]),
                engine=str(row.get("engine") or ""),
            )
        except Exception:
            pass
        return {**row, **exit_info, "ticket": ticket, "status": "closed"}

    def complete_open_trades(self, *, max_hold_bars: int = 72) -> list[dict[str, Any]]:
        closed: list[dict[str, Any]] = []
        for trade_id in self._journal.list_open_paper_trade_ids():
            result = self.complete_trade(trade_id, max_hold_bars=max_hold_bars)
            if result is not None:
                closed.append(result)
        return closed
