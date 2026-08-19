"""Phase 14.3 — session timing quality."""

from __future__ import annotations

SESSION_SCORES: dict[str, float] = {
    "LONDON": 1.0,
    "NEW_YORK": 0.9,
    "ASIA": 0.8,
    "OFF_SESSION": 0.5,
}

_ALIASES: dict[str, str] = {
    "london": "LONDON",
    "new_york": "NEW_YORK",
    "ny": "NEW_YORK",
    "asia": "ASIA",
    "overlap": "LONDON",
    "rollover": "OFF_SESSION",
    "off_hours": "OFF_SESSION",
    "off_session": "OFF_SESSION",
}


def normalize_session(session: str) -> str:
    key = str(session).strip().lower()
    if key.upper() in SESSION_SCORES:
        return key.upper()
    return _ALIASES.get(key, "OFF_SESSION")


def timing_quality_score(session: str) -> tuple[float, str]:
    name = normalize_session(session)
    score = float(SESSION_SCORES.get(name, 0.5))
    return score, f"{name} session score {score}"
