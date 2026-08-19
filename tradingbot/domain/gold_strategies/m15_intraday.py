"""M15 intraday — منطق سودده فعلی (بدون تغییر رفتار)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.price_action import PriceActionSetup, evaluate_setup_at


def evaluate_m15_intraday(
    df: pd.DataFrame, i: int, cfg: dict[str, Any]
) -> PriceActionSetup | None:
    return evaluate_setup_at(df, i, cfg)
