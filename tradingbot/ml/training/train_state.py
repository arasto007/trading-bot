"""Resume state for interrupted Phase 8.6 training runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import training_state_path


@dataclass
class TrainState:
    symbol: str
    timeframe: str
    version: str
    seed: int
    models_completed: list[str] = field(default_factory=list)
    models_pending: list[str] = field(default_factory=list)
    status: str = "pending"
    updated_at_utc: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TrainState:
        return cls(**{k: payload[k] for k in cls.__dataclass_fields__ if k in payload})


class TrainStateStore:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._path = training_state_path(base_dir)

    def load(self) -> TrainState | None:
        if not self._path.is_file():
            return None
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return TrainState.from_dict(payload)

    def save(self, state: TrainState) -> Path:
        state.updated_at_utc = datetime.now(timezone.utc).isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        return self._path

    def clear(self) -> None:
        if self._path.is_file():
            self._path.unlink()

    def mark_model_complete(self, state: TrainState, model_name: str) -> TrainState:
        if model_name in state.models_pending:
            state.models_pending.remove(model_name)
        if model_name not in state.models_completed:
            state.models_completed.append(model_name)
        if not state.models_pending:
            state.status = "completed"
        else:
            state.status = "in_progress"
        self.save(state)
        return state

    def mark_failed(self, state: TrainState, error: str) -> TrainState:
        state.status = "failed"
        state.error = error
        self.save(state)
        return state
