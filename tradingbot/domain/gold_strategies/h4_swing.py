"""H4 swing — BOS+OB و sweep ساختاری؛ بدون FVG (کم‌نویز)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.price_action import (
    PriceActionSetup,
    SetupType,
    Trend,
    evaluate_setup_at,
)


def evaluate_h4_swing(
    df: pd.DataFrame, i: int, cfg: dict[str, Any]
) -> PriceActionSetup | None:
    setup = evaluate_setup_at(df, i, cfg)
    if setup is None:
        return None

    if not bool(cfg.get("H4_ALLOW_FVG", False)) and setup.setup == SetupType.FVG_FILL:
        return None

    if bool(cfg.get("H4_REQUIRE_TREND_ALIGN", True)):
        trend: Trend = df.attrs.get("pa_trend", Trend.RANGE)
        if trend == Trend.BULL and setup.direction != 1:
            return None
        if trend == Trend.BEAR and setup.direction != -1:
            return None

    meta = dict(setup.metadata or {})
    meta["strategy_mode"] = "h4_swing"
    return PriceActionSetup(
        direction=setup.direction,
        setup=setup.setup,
        entry=setup.entry,
        stop_loss=setup.stop_loss,
        take_profit=setup.take_profit,
        confidence=setup.confidence,
        confluence=setup.confluence,
        metadata=meta,
    )
