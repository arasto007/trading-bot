"""Position sizing for Phase 8.7 backtesting (fixed risk %)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskConfig:
    risk_pct: float = 0.005
    tp_r_multiple: float = 2.0
    sl_r_multiple: float = 1.0
    max_open_trades: int = 1

    def __post_init__(self) -> None:
        if not 0.0 < self.risk_pct <= 0.1:
            raise ValueError("risk_pct must be in (0, 0.1]")
        if self.max_open_trades < 1:
            raise ValueError("max_open_trades must be >= 1")


@dataclass
class PositionSize:
    risk_amount: float
    risk_unit: float
    notional_risk: float

    @property
    def units(self) -> float:
        if self.risk_unit <= 0:
            return 0.0
        return self.risk_amount / self.risk_unit


class RiskManager:
    """Fixed fractional risk sizing aligned with dataset 1R / 2R logic."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def compute_position(
        self,
        equity: float,
        risk_unit: float,
        *,
        atr: float | None = None,
    ) -> PositionSize:
        if equity <= 0:
            raise ValueError("equity must be positive")
        unit = float(risk_unit)
        if atr is not None and atr > 0:
            unit = max(unit, float(atr))
        if unit <= 0:
            raise ValueError("risk_unit must be positive")
        risk_amount = equity * self.config.risk_pct
        return PositionSize(
            risk_amount=risk_amount,
            risk_unit=unit,
            notional_risk=risk_amount,
        )

    def pnl_from_label(
        self,
        label: int,
        risk_amount: float,
        *,
        costs: float = 0.0,
    ) -> tuple[float, float]:
        """Return (pnl_currency, pnl_r) from historical label outcome."""
        if label == 1:
            pnl_r = self.config.tp_r_multiple
        else:
            pnl_r = -self.config.sl_r_multiple
        pnl = (pnl_r * risk_amount) - costs
        return pnl, pnl_r
