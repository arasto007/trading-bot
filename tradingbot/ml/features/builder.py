"""Feature builder — orchestrates all feature families on M5 anchor timeframe."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.config.price_action import get_price_action_config
from tradingbot.ml.data.roles import CONTEXT_TIMEFRAME, ENTRY_TIMEFRAME, HIGHER_TIMEFRAME_BIAS
from tradingbot.ml.features import context, microstructure, momentum, price_action, session, smc, trend, volatility
from tradingbot.ml.features.registry.registry import all_features, feature_names, validate_integrity

logger = logging.getLogger(__name__)

_MIN_WARMUP = 60

_FAMILIES = [
    trend.TrendFeatures(),
    momentum.MomentumFeatures(),
    volatility.VolatilityFeatures(),
    price_action.PriceActionFeatures(),
    smc.SmcStructureFeatures(),
    session.SessionFeatures(),
    microstructure.MicrostructureFeatures(),
    context.HtfContextFeatures(),
]


def _build_spread_series(spread_df: pd.DataFrame | None) -> pd.Series | None:
    if spread_df is None or spread_df.empty:
        return None
    if "ts_utc" in spread_df.columns:
        idx = pd.to_datetime(spread_df["ts_utc"], utc=True)
        return pd.Series(spread_df["spread_pips"].values, index=idx).sort_index()
    if isinstance(spread_df.index, pd.DatetimeIndex):
        col = "spread_pips" if "spread_pips" in spread_df.columns else spread_df.columns[0]
        return spread_df[col].sort_index()
    return None


class FeatureBuilder:
    """
    Build causal bar-level features anchored on entry timeframe (M5).

    All families implement compute_features(df, index) with no future access.
    """

    def __init__(self, symbol: str = "XAUUSD", base_dir: str | None = None) -> None:
        self.symbol = symbol.upper()
        self.base_dir = base_dir
        self._pa_cfg = get_price_action_config(symbol, ENTRY_TIMEFRAME)

    @staticmethod
    def registered_feature_names() -> list[str]:
        return feature_names()

    @staticmethod
    def validate_registry() -> list[str]:
        return validate_integrity()

    def compute_at(
        self,
        m5_df: pd.DataFrame,
        index: int,
        *,
        h4_df: pd.DataFrame | None = None,
        m15_df: pd.DataFrame | None = None,
        spread_series: pd.Series | None = None,
    ) -> dict[str, float]:
        if index < 0 or m5_df is None or m5_df.empty:
            return {name: 0.0 for name in feature_names()}

        kwargs: dict[str, Any] = {
            "symbol": self.symbol,
            "pa_cfg": self._pa_cfg,
            "h4_df": h4_df,
            "m15_df": m15_df,
            "spread_series": spread_series,
        }

        row: dict[str, float] = {}
        for family in _FAMILIES:
            if family.family_name == "htf_context":
                feats = family.compute_features(m5_df, index, **kwargs)
            elif family.family_name == "smc_structure":
                feats = family.compute_features(m5_df, index, pa_cfg=self._pa_cfg)
            elif family.family_name == "session":
                feats = family.compute_features(m5_df, index, symbol=self.symbol)
            elif family.family_name == "microstructure":
                feats = family.compute_features(m5_df, index, spread_series=spread_series)
            else:
                feats = family.compute_features(m5_df, index)
            row.update(feats)
        return row

    def build_dataframe(
        self,
        m5_df: pd.DataFrame,
        *,
        h4_df: pd.DataFrame | None = None,
        m15_df: pd.DataFrame | None = None,
        spread_df: pd.DataFrame | None = None,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> pd.DataFrame:
        if m5_df is None or m5_df.empty:
            return pd.DataFrame()

        spread_series = _build_spread_series(spread_df)
        start = max(_MIN_WARMUP, start_index or _MIN_WARMUP)
        end = len(m5_df) - 1 if end_index is None else min(end_index, len(m5_df) - 1)

        rows: list[dict[str, float]] = []
        index_list: list = []
        for i in range(start, end + 1):
            feats = self.compute_at(m5_df, i, h4_df=h4_df, m15_df=m15_df, spread_series=spread_series)
            rows.append(feats)
            index_list.append(m5_df.index[i])

        out = pd.DataFrame(rows, index=pd.DatetimeIndex(index_list, tz="UTC"))
        out.index.name = "time"
        return out

    def build_from_stores(
        self,
        candle_store,
        spread_store=None,
        *,
        anchor_tf: str = ENTRY_TIMEFRAME,
    ) -> pd.DataFrame:
        m5 = candle_store.load(self.symbol, anchor_tf)
        h4 = candle_store.load(self.symbol, HIGHER_TIMEFRAME_BIAS)
        m15 = candle_store.load(self.symbol, CONTEXT_TIMEFRAME)

        spread_df = None
        if spread_store is not None:
            days = spread_store.list_days(self.symbol) if hasattr(spread_store, "list_days") else []
            frames = []
            for day in days[-30:]:
                part = spread_store.load_day(self.symbol, day) if hasattr(spread_store, "load_day") else None
                if part is not None and not part.empty:
                    frames.append(part)
            if frames:
                spread_df = pd.concat(frames).sort_index()

        return self.build_dataframe(m5, h4_df=h4, m15_df=m15, spread_df=spread_df)

    def registry_summary(self) -> list[dict[str, str]]:
        return [d.to_dict() for d in all_features()]
