"""Phase 15A — canonical unified signal schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class UnifiedSignal:
  """Single canonical signal consumed by all future integration layers."""

  engine: str | None
  regime: str
  direction: str
  confidence: float
  quality: float
  risk: float
  sl: float | None = None
  tp: float | None = None
  reason: list[str] = field(default_factory=list)
  trace: list[str] = field(default_factory=list)
  checksum: str = ""
  timestamp: str = ""

  def __post_init__(self) -> None:
    if not self.timestamp:
      self.timestamp = datetime.now(timezone.utc).isoformat()
    if not self.checksum:
      self.checksum = self.compute_checksum()

  def compute_checksum(self) -> str:
    payload = {
      "engine": self.engine,
      "regime": self.regime,
      "direction": self.direction,
      "confidence": round(self.confidence, 6),
      "quality": round(self.quality, 6),
      "risk": round(self.risk, 6),
      "timestamp": self.timestamp,
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> "UnifiedSignal":
    return cls(
      engine=data.get("engine"),
      regime=str(data.get("regime", "NO_TRADE")),
      direction=str(data.get("direction", "HOLD")),
      confidence=float(data.get("confidence", 0.0)),
      quality=float(data.get("quality", 0.0)),
      risk=float(data.get("risk", 0.0)),
      sl=data.get("sl"),
      tp=data.get("tp"),
      reason=list(data.get("reason", [])),
      trace=list(data.get("trace", [])),
      checksum=str(data.get("checksum", "")),
      timestamp=str(data.get("timestamp", "")),
    )

  def validate_schema(self) -> list[str]:
    errors: list[str] = []
    if self.direction not in ("BUY", "SELL", "HOLD"):
      errors.append(f"invalid direction: {self.direction}")
    if not 0.0 <= self.confidence <= 1.0:
      errors.append("confidence out of range")
    if not 0.0 <= self.quality <= 1.0:
      errors.append("quality out of range")
    if self.risk < 0:
      errors.append("risk negative")
    if self.checksum != self.compute_checksum():
      errors.append("checksum mismatch")
    return errors


SIGNAL_SCHEMA_VERSION = "1.0"

SIGNAL_SCHEMA: dict[str, Any] = {
  "version": SIGNAL_SCHEMA_VERSION,
  "required_fields": [
    "engine", "regime", "direction", "confidence", "quality", "risk",
    "sl", "tp", "reason", "trace", "checksum", "timestamp",
  ],
  "direction_values": ["BUY", "SELL", "HOLD"],
  "regime_values": ["TREND", "RANGE", "HIGH_VOLATILITY", "NO_TRADE"],
}
