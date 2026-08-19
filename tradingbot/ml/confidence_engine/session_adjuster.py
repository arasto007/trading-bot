"""Phase 14.2A — session quality adjustments (Phase 11.5 inspired)."""

from __future__ import annotations

from tradingbot.ml.confidence_engine.calibration_types import SessionName

DEFAULT_SESSION_FACTORS: dict[str, float] = {
    "ASIA": 1.10,
    "LONDON": 1.00,
    "NEW_YORK": 1.05,
    "OFF_SESSION": 0.85,
}

_SESSION_ALIASES: dict[str, SessionName] = {
    "asia": "ASIA",
    "london": "LONDON",
    "new_york": "NEW_YORK",
    "ny": "NEW_YORK",
    "overlap": "LONDON",
    "rollover": "OFF_SESSION",
    "off_hours": "OFF_SESSION",
    "off_session": "OFF_SESSION",
}


class SessionAdjuster:
    def __init__(self, factors: dict[str, float] | None = None) -> None:
        self.factors = dict(factors or DEFAULT_SESSION_FACTORS)

    def normalize(self, session: str) -> SessionName:
        key = str(session).strip().lower()
        if key.upper() in self.factors:
            return key.upper()  # type: ignore[return-value]
        return _SESSION_ALIASES.get(key, "OFF_SESSION")

    def factor(self, session: str) -> tuple[float, str, SessionName]:
        name = self.normalize(session)
        mult = float(self.factors.get(name, 1.0))
        pct = int(round((mult - 1.0) * 100))
        label = f"{name} session {pct:+d}%"
        return mult, label, name
