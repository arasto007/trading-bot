"""Session feature family — time-of-day and kill-zone market state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from tradingbot.ml.data.session_utils import classify_session, session_record_at
from tradingbot.ml.features.base import FeatureDefinition, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "session"
_SOURCE = "candle timestamps"

_DEFINITIONS = [
    FeatureDefinition("session_asia", _SOURCE, "1 if Asia session else 0", "1.0", _FAMILY),
    FeatureDefinition("session_london", _SOURCE, "1 if London session else 0", "1.0", _FAMILY),
    FeatureDefinition("session_ny", _SOURCE, "1 if New York session else 0", "1.0", _FAMILY),
    FeatureDefinition("session_off", _SOURCE, "1 if off-hours session else 0", "1.0", _FAMILY),
    FeatureDefinition("in_london_kill", _SOURCE, "1 if London kill zone (07-10 UTC)", "1.0", _FAMILY),
    FeatureDefinition("in_ny_kill", _SOURCE, "1 if NY kill zone (12-15 UTC)", "1.0", _FAMILY),
    FeatureDefinition("is_friday", _SOURCE, "1 if Friday else 0", "1.0", _FAMILY),
    FeatureDefinition("hour_utc_norm", _SOURCE, "Hour UTC normalized 0-1", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)

_SESSION_FLAGS = {
    "asia": "session_asia",
    "london": "session_london",
    "new_york": "session_ny",
    "off_hours": "session_off",
}


class SessionFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        work = truncated_df(df, index)
        out = {d.name: 0.0 for d in _DEFINITIONS}
        if work is None or work.empty:
            return out

        ts = work.index[-1]
        if not isinstance(ts, datetime):
            ts = ts.to_pydatetime()  # type: ignore[union-attr]

        symbol = kwargs.get("symbol", "XAUUSD")
        rec = session_record_at(ts, symbol)
        session = rec.session
        flag_key = _SESSION_FLAGS.get(session)
        if flag_key:
            out[flag_key] = 1.0

        out["in_london_kill"] = 1.0 if rec.in_london_kill else 0.0
        out["in_ny_kill"] = 1.0 if rec.in_ny_kill else 0.0
        out["is_friday"] = 1.0 if rec.is_friday else 0.0
        out["hour_utc_norm"] = round(rec.hour_utc / 23.0, 4)
        return out


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return SessionFeatures().compute_features(df, index, **kwargs)
