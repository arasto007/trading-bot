"""Phase 14.2B — session-based risk adjustment."""

from __future__ import annotations

SESSION_RISK_FACTORS: dict[str, float] = {
    "ASIA": 1.0,
    "LONDON": 1.10,
    "NEW_YORK": 1.05,
    "OFF_SESSION": 0.80,
}

_ALIASES: dict[str, str] = {
    "asia": "ASIA",
    "london": "LONDON",
    "new_york": "NEW_YORK",
    "ny": "NEW_YORK",
    "overlap": "LONDON",
    "rollover": "OFF_SESSION",
    "off_hours": "OFF_SESSION",
    "off_session": "OFF_SESSION",
}


def normalize_session(session: str) -> str:
    key = str(session).strip().lower()
    if key.upper() in SESSION_RISK_FACTORS:
        return key.upper()
    return _ALIASES.get(key, "OFF_SESSION")


def session_risk_multiplier(session: str) -> tuple[float, str]:
    name = normalize_session(session)
    factor = float(SESSION_RISK_FACTORS.get(name, 1.0))
    pct = int(round((factor - 1.0) * 100))
    return factor, f"{name} session {pct:+d}%"
