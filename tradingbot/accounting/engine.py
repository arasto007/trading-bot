"""Accounting engine — orchestrates sizing, PnL, and ledger updates."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from tradingbot.accounting.broker_constraints import BrokerConstraints, constraints_for_symbol
from tradingbot.accounting.ledger import AccountingLedger, ClosedTradeRecord
from tradingbot.accounting.metrics import compute_performance_metrics
from tradingbot.accounting.position_sizing import PositionSizingResult, resolve_position_size


class AccountingEngine:
    """Single source of truth for all replay, paper, and performance accounting."""

    def __init__(
        self,
        *,
        initial_balance: float,
        symbol: str = "XAUUSD",
        constraints: BrokerConstraints | None = None,
    ) -> None:
        self.symbol = symbol
        self.constraints = constraints or constraints_for_symbol(symbol)
        self.ledger = AccountingLedger(initial_balance=initial_balance)

    @property
    def balance(self) -> float:
        return self.ledger.balance

    @property
    def equity(self) -> float:
        return self.ledger.equity

    @property
    def realized_pnl(self) -> float:
        return self.ledger.realized_pnl

    def resolve_lot(
        self,
        *,
        configured_risk_percent: float,
        entry_price: float,
        stop_loss: float | None,
        requested_lot: float | None = None,
    ) -> PositionSizingResult:
        return resolve_position_size(
            equity=self.ledger.equity,
            configured_risk_percent=configured_risk_percent,
            entry_price=entry_price,
            stop_loss=stop_loss,
            symbol=self.symbol,
            constraints=self.constraints,
            requested_lot=requested_lot,
        )

    def close_trade(
        self,
        *,
        exit_info: dict[str, Any],
        entry_timestamp: str,
        entry_price: float,
        direction: str,
        lot: float,
        sl: float | None,
        tp: float | None,
        sizing: PositionSizingResult | dict[str, Any] | None = None,
        regime: str = "",
        engine: str = "",
        confidence: float = 0.0,
        risk_percent: float = 0.0,
        bar_index: int | None = None,
        timeframe: str = "M5",
        trade_id: str | None = None,
    ) -> ClosedTradeRecord:
        sizing_dict: dict[str, Any]
        actual_risk = risk_percent
        risk_dev = 0.0
        min_lot = False
        if isinstance(sizing, PositionSizingResult):
            sizing_dict = sizing.to_dict()
            actual_risk = sizing.actual_risk_percent
            risk_dev = sizing.risk_deviation_percent
            min_lot = sizing.min_lot_limit_applied
        elif isinstance(sizing, dict):
            sizing_dict = sizing
            actual_risk = float(sizing.get("actual_risk_percent", risk_percent))
            risk_dev = float(sizing.get("risk_deviation_percent", 0))
            min_lot = bool(sizing.get("min_lot_limit_applied", False))
        else:
            sizing_dict = {}

        record = ClosedTradeRecord(
            trade_id=trade_id or uuid4().hex[:12],
            timestamp=entry_timestamp,
            exit_timestamp=str(exit_info.get("exit_timestamp", "")),
            symbol=self.symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=float(exit_info.get("exit_price", 0)),
            lot=lot,
            pnl=float(exit_info.get("pnl", 0)),
            pnl_r=float(exit_info.get("pnl_r", 0)),
            sl=sl,
            tp=tp,
            exit_reason=str(exit_info.get("exit_reason", "")),
            duration_bars=int(exit_info.get("duration_bars", 0)),
            duration_sec=int(exit_info.get("duration_sec", 0)),
            mae=float(exit_info.get("mae", 0)),
            mfe=float(exit_info.get("mfe", 0)),
            spread=float(exit_info.get("spread", 0)),
            partial_close_applied=bool(exit_info.get("partial_close_applied")),
            partial_pnl=float(exit_info.get("partial_pnl", 0)),
            rr=exit_info.get("rr"),
            regime=regime,
            engine=engine,
            confidence=confidence,
            risk_percent=risk_percent,
            actual_risk_percent=actual_risk,
            risk_deviation_percent=risk_dev,
            min_lot_limit_applied=min_lot,
            sizing=sizing_dict,
            bar_index=bar_index,
            timeframe=timeframe,
        )
        record.to_dict()
        self.ledger.apply_close(record)
        return record

    def performance_metrics(self, *, timeframe: str = "M5") -> dict[str, Any]:
        return compute_performance_metrics(self.ledger, timeframe=timeframe)

    def validate_against(self, other: dict[str, Any], *, tolerance: float = 0.01) -> dict[str, Any]:
        snap = self.ledger.snapshot()
        checks = {
            "balance": abs(snap["balance"] - float(other.get("balance", other.get("final_balance", 0)))) <= tolerance,
            "realized_pnl": abs(snap["realized_pnl"] - float(other.get("realized_pnl", other.get("net_profit", 0)))) <= tolerance,
            "trade_count": snap["trade_count"] == int(other.get("trade_count", other.get("completed_trades", 0))),
            "max_drawdown_pct": abs(snap["max_drawdown_pct"] - float(other.get("max_drawdown_pct", 0))) <= 0.02,
        }
        return {"checks": checks, "all_pass": all(checks.values()), "engine": snap, "other": other}

    def export(self) -> dict[str, Any]:
        perf = self.performance_metrics()
        return {
            "ledger": self.ledger.snapshot(),
            "trades": self.ledger.export_trades(),
            "balance_curve": self.ledger.balance_curve,
            "equity_curve": self.ledger.equity_curve,
            "drawdown_curve": self.ledger.drawdown_curve,
            "performance": perf,
        }
