"""مسیریاب استراتژی طلا — M5 london sweep / M15 intraday."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.gold_strategies.h4_swing import evaluate_h4_swing
from tradingbot.domain.gold_strategies.m15_intraday import evaluate_m15_intraday
from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
from tradingbot.domain.gold_strategies.m5_scalp import evaluate_m5_scalp
from tradingbot.domain.price_action import PriceActionSetup


def _resolve_mode(cfg: dict[str, Any], timeframe: str) -> str:
    mode = str(cfg.get("GOLD_STRATEGY_MODE", "") or "").lower().strip()
    if mode in ("london_sweep", "m5_london_sweep", "asian_sweep"):
        return "london_sweep"
    if mode in ("scalp", "m5_scalp"):
        return "scalp"
    if mode in ("h4_swing", "swing", "h4"):
        return "h4_swing"
    if mode in ("intraday", "m15_intraday", "m15"):
        return "intraday"
    tf = (timeframe or "").upper().replace("5M", "M5").replace("15M", "M15").replace("4H", "H4")
    if tf == "M5":
        return "london_sweep"
    if tf == "H4":
        return "h4_swing"
    return "intraday"


def evaluate_gold_setup(
    df: pd.DataFrame,
    i: int,
    cfg: dict[str, Any],
    *,
    timeframe: str = "M15",
) -> PriceActionSetup | None:
    mode = _resolve_mode(cfg, timeframe)
    setup: PriceActionSetup | None = None
    if mode == "london_sweep":
        setup = evaluate_m5_london_sweep(df, i, cfg)
    elif mode == "scalp":
        setup = evaluate_m5_scalp(df, i, cfg)
    elif mode == "h4_swing":
        setup = evaluate_h4_swing(df, i, cfg)
    else:
        setup = evaluate_m15_intraday(df, i, cfg)

    if setup is None:
        return None

    from tradingbot.domain.pa_hardening import apply_setup_hardening

    return apply_setup_hardening(df, i, cfg, setup, timeframe=timeframe)
