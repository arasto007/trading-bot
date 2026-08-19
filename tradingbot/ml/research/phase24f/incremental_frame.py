"""
Phase 24F — incremental unified frame (research prototype).

Does NOT modify production. Proves parity against build_unified_frame().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features


def production_unified_frame(candles: pd.DataFrame, dataset: pd.DataFrame | None) -> pd.DataFrame:
    """Production-equivalent path (PipelineCache includes attach_top5 for v41)."""
    tail = candles.tail(300).copy()
    return attach_top5_features(build_unified_frame(tail, dataset))


@dataclass
class IncrementalUnifiedState:
    unified: pd.DataFrame
    last_bar_timestamp: Any
    window_len: int


def incremental_unified_frame_step(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    state: IncrementalUnifiedState | None,
) -> tuple[pd.DataFrame, IncrementalUnifiedState]:
    """
    Research incremental algorithm (design spec):

    1. Reuse previous unified frame rows 1..N-1 unchanged
    2. Drop row 0 (oldest bar left the 300-candle window)
    3. Append new last row computed from current candle window
    4. Re-run attach_top5 on the assembled frame (regime/trend_age coupling)

    Last row feature values are taken from a full rebuild's final row during
    parity proof — production integration would compute that row incrementally.

    IMPORTANT (Phase 24F finding): reusing body rows from the previous cycle
    is NOT parity-safe. Consecutive full rebuilds on a sliding tail(300) window
    produce different values at the same timestamp (EMA200 delta up to ~2.3).
    """
    tail = candles.tail(300).copy()
    full = production_unified_frame(tail, dataset)

    if state is None or len(state.unified) == 0:
        return full, IncrementalUnifiedState(
            unified=full.copy(),
            last_bar_timestamp=tail.index[-1],
            window_len=len(tail),
        )

    if tail.index[-1] == state.last_bar_timestamp:
        return state.unified.copy(), state

    if len(state.unified) != len(full):
        return full, IncrementalUnifiedState(
            unified=full.copy(),
            last_bar_timestamp=tail.index[-1],
            window_len=len(tail),
        )

    body = state.unified.iloc[1:].reset_index(drop=True)
    new_row = full.iloc[[-1]].reset_index(drop=True)
    assembled = pd.concat([body, new_row], ignore_index=True)
    assembled = assembled.sort_values("timestamp").reset_index(drop=True)

    # trend_age on last row depends on regime sequence — re-attach top5 on assembled frame
    inc = attach_top5_features(assembled)

    return inc, IncrementalUnifiedState(
        unified=inc.copy(),
        last_bar_timestamp=tail.index[-1],
        window_len=len(tail),
    )
