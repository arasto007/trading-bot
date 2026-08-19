"""Shadow mode engine — ML predictions alongside existing system (no influence)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tradingbot.ml.decision.logger import DecisionLogger, shadow_dir, shadow_log_path
from tradingbot.ml.decision.predictor import MLPredictor
from tradingbot.ml.decision.schema import MLDecision, utc_now_iso


@dataclass
class ShadowRecord:
    timestamp: str
    symbol: str
    timeframe: str
    model_name: str
    ml_prediction: int
    ml_probability: float
    ml_direction: str
    ml_accepted: bool
    system_signal: str | None = None
    agreement: bool | None = None
    decision: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowEngine:
    """
    Run ML decision layer in parallel with existing system.

    Records comparison to data/ml/shadow/ — does not affect live execution.
    """

    def __init__(
        self,
        predictor: MLPredictor,
        *,
        base_dir: str | Path | None = None,
        log_decisions: bool = True,
    ) -> None:
        self.predictor = predictor
        self.base_dir = base_dir
        self.log_decisions = log_decisions
        shadow_dir(base_dir).mkdir(parents=True, exist_ok=True)
        self._decision_logger = DecisionLogger(predictor.symbol, base_dir)

    @property
    def shadow_path(self) -> Path:
        return shadow_log_path(self.predictor.symbol, self.base_dir)

    def run(
        self,
        feature_row: dict[str, Any],
        *,
        system_signal: str | None = None,
    ) -> ShadowRecord:
        decision = self.predictor.predict_row(feature_row)

        agreement: bool | None = None
        if system_signal is not None:
            agreement = self._check_agreement(decision, system_signal)

        record = ShadowRecord(
            timestamp=decision.timestamp or utc_now_iso(),
            symbol=decision.symbol,
            timeframe=decision.timeframe,
            model_name=decision.model_name,
            ml_prediction=decision.prediction,
            ml_probability=decision.probability,
            ml_direction=decision.direction,
            ml_accepted=decision.accepted,
            system_signal=system_signal,
            agreement=agreement,
            decision=decision.to_dict(),
        )

        self._append_shadow(record)
        if self.log_decisions:
            self._decision_logger.log(decision)
        return record

    @staticmethod
    def _check_agreement(decision: MLDecision, system_signal: str) -> bool:
        sys_norm = system_signal.upper().strip()
        if not decision.accepted:
            return sys_norm in ("HOLD", "NONE", "NEUTRAL", "")
        if decision.direction == "BUY":
            return sys_norm in ("BUY", "LONG")
        if decision.direction == "SELL":
            return sys_norm in ("SELL", "SHORT")
        return sys_norm in ("HOLD", "NEUTRAL")

    def _append_shadow(self, record: ShadowRecord) -> None:
        with self.shadow_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def read_shadow_log(self) -> list[dict[str, Any]]:
        if not self.shadow_path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.shadow_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
