"""Dynamic position sizing with broker constraint enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingbot.accounting.broker_constraints import BrokerConstraints, constraints_for_symbol


@dataclass(frozen=True)
class PositionSizingResult:
    configured_risk_percent: float
    requested_lot: float
    executed_lot: float
    dollar_risk_configured: float
    dollar_risk_actual: float
    actual_risk_percent: float
    risk_deviation_percent: float
    min_lot_limit_applied: bool
    limit_reason: str | None
    sl_distance: float
    equity_at_entry: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured_risk_percent": self.configured_risk_percent,
            "requested_lot": self.requested_lot,
            "executed_lot": self.executed_lot,
            "dollar_risk_configured": self.dollar_risk_configured,
            "dollar_risk_actual": self.dollar_risk_actual,
            "actual_risk_percent": self.actual_risk_percent,
            "risk_deviation_percent": self.risk_deviation_percent,
            "min_lot_limit_applied": self.min_lot_limit_applied,
            "limit_reason": self.limit_reason,
            "sl_distance": self.sl_distance,
            "equity_at_entry": self.equity_at_entry,
        }


def resolve_position_size(
    *,
    equity: float,
    configured_risk_percent: float,
    entry_price: float,
    stop_loss: float | None,
    symbol: str,
    constraints: BrokerConstraints | None = None,
    requested_lot: float | None = None,
) -> PositionSizingResult:
    """
    Risk % → dollar risk → SL distance → lot → broker constraints.

    If calculated lot < broker minimum, records MIN_LOT_LIMIT and reports
    actual risk separately from configured risk.
    """
    bc = constraints or constraints_for_symbol(symbol)
    sl_dist = abs(entry_price - float(stop_loss)) if stop_loss is not None else 0.0
    risk_frac = configured_risk_percent / 100.0
    dollar_risk_target = round(equity * risk_frac, 4) if equity > 0 else 0.0

    if sl_dist <= 0 or bc.contract_size <= 0:
        lot_calc = bc.min_lot
    else:
        lot_calc = dollar_risk_target / (sl_dist * bc.contract_size)

    lot_clamped = bc.clamp_lot(lot_calc)
    min_applied = lot_calc < bc.min_lot - 1e-9
    limit_reason = "MIN_LOT_LIMIT" if min_applied else None

    executed = requested_lot if requested_lot is not None and requested_lot > 0 else lot_clamped
    executed = bc.clamp_lot(executed)

    dollar_actual = bc.dollar_risk(executed, sl_dist)
    actual_pct = bc.risk_percent_of(dollar_actual, equity)
    deviation = round(actual_pct - configured_risk_percent, 4)

    return PositionSizingResult(
        configured_risk_percent=round(configured_risk_percent, 4),
        requested_lot=round(lot_calc, 6),
        executed_lot=executed,
        dollar_risk_configured=dollar_risk_target,
        dollar_risk_actual=dollar_actual,
        actual_risk_percent=actual_pct,
        risk_deviation_percent=deviation,
        min_lot_limit_applied=min_applied or (executed == bc.min_lot and lot_calc < bc.min_lot),
        limit_reason=limit_reason,
        sl_distance=round(sl_dist, 4),
        equity_at_entry=round(equity, 4),
    )
