"""Phase 22C — exact HOLD-stage counters for ML → RiskGate funnel."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class HoldStage(str, Enum):
    DECISION = "decision_hold"
    CALIBRATION = "calibration_hold"
    TRADE_QUALITY = "trade_quality_hold"
    RSI_FILTER = "rsi_filter_hold"
    ADX_FILTER = "adx_filter_hold"
    META = "meta_hold"
    RISK_GATE = "riskgate_hold"


@dataclass
class HoldChainCounters:
    """Thread-safe exact counters — one increment per bar/signal evaluation."""

    bars_evaluated: int = 0
    buy_emitted: int = 0
    sell_emitted: int = 0
    decision_hold: int = 0
    calibration_hold: int = 0
    trade_quality_hold: int = 0
    rsi_filter_hold: int = 0
    adx_filter_hold: int = 0
    meta_hold: int = 0
    riskgate_hold: int = 0
    riskgate_block_reasons: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_bar(self) -> None:
        with self._lock:
            self.bars_evaluated += 1

    def record_buy(self) -> None:
        with self._lock:
            self.buy_emitted += 1

    def record_sell(self) -> None:
        with self._lock:
            self.sell_emitted += 1

    def record(self, stage: HoldStage, *, reason: str | None = None) -> None:
        with self._lock:
            attr = stage.value
            setattr(self, attr, int(getattr(self, attr)) + 1)
            if stage == HoldStage.RISK_GATE and reason:
                key = reason.split("(")[0].strip()
                self.riskgate_block_reasons[key] = self.riskgate_block_reasons.get(key, 0) + 1

    def reset(self) -> None:
        with self._lock:
            self.bars_evaluated = 0
            self.buy_emitted = 0
            self.sell_emitted = 0
            self.decision_hold = 0
            self.calibration_hold = 0
            self.trade_quality_hold = 0
            self.rsi_filter_hold = 0
            self.adx_filter_hold = 0
            self.meta_hold = 0
            self.riskgate_hold = 0
            self.riskgate_block_reasons = {}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total_hold = (
                self.decision_hold
                + self.calibration_hold
                + self.trade_quality_hold
                + self.rsi_filter_hold
                + self.adx_filter_hold
            )
            ml_signals = self.buy_emitted + self.sell_emitted
            return {
                "bars_evaluated": self.bars_evaluated,
                "buy_emitted": self.buy_emitted,
                "sell_emitted": self.sell_emitted,
                "ml_signals": ml_signals,
                "ml_hold_stages": {
                    "decision_hold": self.decision_hold,
                    "calibration_hold": self.calibration_hold,
                    "trade_quality_hold": self.trade_quality_hold,
                    "rsi_filter_hold": self.rsi_filter_hold,
                    "adx_filter_hold": self.adx_filter_hold,
                },
                "ml_hold_total": total_hold,
                "meta_hold": self.meta_hold,
                "riskgate_hold": self.riskgate_hold,
                "riskgate_block_reasons": dict(self.riskgate_block_reasons),
            }

    def write_json(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
        return out


_GLOBAL = HoldChainCounters()
_ENABLED = True


def hold_chain_enabled() -> bool:
    return _ENABLED


def set_hold_chain_enabled(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = enabled


def get_hold_chain() -> HoldChainCounters:
    return _GLOBAL


def reset_hold_chain() -> None:
    _GLOBAL.reset()
