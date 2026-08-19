"""Phase B1 — VOL context engine (quality only, no BUY/SELL)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.live_l2.edge_discovery_round2 import _prepare_frame_round2
from tradingbot.strategies.vol_regime_signal import prepare_frame as _prepare_vol_frame

# ATR percentile bands on 0–100 scale (from rolling rank × 100).
ATR_MARKET_OK_MIN = 40.0
ATR_MARKET_OK_MAX = 70.0
ATR_EXPANSION_MIN = 70.0
ATR_EXPANSION_MAX = 85.0
SPREAD_P75_THRESHOLD = 0.75  # spread_pct rank above this → market not OK


@dataclass(frozen=True)
class VolContext:
    """Read-only market quality snapshot — never emits trade direction."""

    market_ok: bool
    expansion_strength: float  # 0..1
    compression_strength: float  # 0..1
    session_quality: float  # 0..1
    atr_percentile: float  # 0..100
    spread_quality: float  # 0..1

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_ok": self.market_ok,
            "expansion_strength": round(self.expansion_strength, 4),
            "compression_strength": round(self.compression_strength, 4),
            "session_quality": round(self.session_quality, 4),
            "atr_percentile": round(self.atr_percentile, 2),
            "spread_quality": round(self.spread_quality, 4),
            "quality_score": round(self.quality_score(), 4),
        }

    def quality_score(self) -> float:
        """Composite 0–1 PA quality gate (telemetry / research)."""
        atr_s = _tradeable_atr_score(self.atr_percentile)
        if self.atr_percentile >= ATR_EXPANSION_MIN:
            atr_s = max(atr_s, self.expansion_strength)
        return float(
            np.clip(
                0.35 * atr_s
                + 0.25 * self.expansion_strength
                + 0.25 * self.session_quality
                + 0.15 * self.spread_quality,
                0.0,
                1.0,
            )
        )

    def passes_pa_quality_gate(self, *, threshold: float = 0.33) -> bool:
        """True when composite vol context supports PA entry."""
        return self.quality_score() >= threshold


def prepare_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Build indicator frame (reuses VOL frame prep — no direction logic)."""
    return _prepare_vol_frame(candles)


def _session_quality(hour_utc: int) -> float:
    """UTC session quality tiers for XAUUSD."""
    if 7 <= hour_utc < 12:
        return 1.0  # London
    if 12 <= hour_utc < 17:
        return 0.8  # London/NY overlap
    if 17 <= hour_utc < 22:
        return 0.5  # NY late
    return 0.2  # Asia / off-hours


def _atr_percentile_100(row: pd.Series) -> float:
    raw = float(row.get("atr_pct", np.nan))
    if not np.isfinite(raw):
        return float("nan")
    # Frame stores 0–1 rank; spec bands use 0–100.
    return float(np.clip(raw * 100.0, 0.0, 100.0))


def _tradeable_atr_score(atr_pct: float) -> float:
    """PA-friendly volatility inside the 40–70 tradeable band."""
    if not np.isfinite(atr_pct):
        return 0.0
    if ATR_MARKET_OK_MIN <= atr_pct <= ATR_MARKET_OK_MAX:
        return float(np.clip(0.35 + 0.65 * (1.0 - abs(atr_pct - 58.0) / 17.0), 0.0, 1.0))
    return 0.0


def _expansion_strength(atr_pct: float) -> float:
    """High in the (70, 85] expansion band; ramps through the 40–70 tradeable band."""
    if not np.isfinite(atr_pct):
        return 0.0
    if ATR_MARKET_OK_MIN <= atr_pct <= ATR_MARKET_OK_MAX:
        return _tradeable_atr_score(atr_pct)
    if ATR_EXPANSION_MIN < atr_pct <= ATR_EXPANSION_MAX:
        center = (ATR_EXPANSION_MIN + ATR_EXPANSION_MAX) / 2.0
        half = (ATR_EXPANSION_MAX - ATR_EXPANSION_MIN) / 2.0
        return float(np.clip(0.75 + 0.25 * (1.0 - abs(atr_pct - center) / half), 0.0, 1.0))
    if atr_pct < ATR_MARKET_OK_MIN:
        return float(np.clip(atr_pct / ATR_MARKET_OK_MIN * 0.25, 0.0, 0.25))
    return float(np.clip(max(0.0, 0.5 - (atr_pct - ATR_EXPANSION_MAX) / 30.0), 0.0, 0.5))


def _compression_strength(atr_pct: float) -> float:
    """High when volatility is compressed (ATR percentile below ~40)."""
    if not np.isfinite(atr_pct):
        return 0.0
    if atr_pct >= ATR_MARKET_OK_MIN:
        return float(np.clip(max(0.0, 1.0 - (atr_pct - ATR_MARKET_OK_MIN) / 60.0), 0.0, 0.5))
    return float(np.clip(1.0 - atr_pct / ATR_MARKET_OK_MIN, 0.0, 1.0))


def _spread_quality(row: pd.Series) -> tuple[float, bool]:
    spread_pct = float(row.get("spread_pct", np.nan))
    spread_proxy = float(row.get("spread_proxy", np.nan))
    if np.isfinite(spread_pct):
        quality = float(np.clip(1.0 - spread_pct, 0.0, 1.0))
        above_p75 = spread_pct > SPREAD_P75_THRESHOLD
        return quality, above_p75
    if np.isfinite(spread_proxy):
        return 0.5, False
    return 0.0, False


def evaluate_vol_context(frame: pd.DataFrame, idx: int) -> VolContext:
    """Evaluate market quality context at a bar index on a prepared frame."""
    if frame.empty or idx < 0 or idx >= len(frame):
        return VolContext(
            market_ok=False,
            expansion_strength=0.0,
            compression_strength=0.0,
            session_quality=0.0,
            atr_percentile=float("nan"),
            spread_quality=0.0,
        )

    row = frame.iloc[idx]
    atr_pct = _atr_percentile_100(row)
    spread_q, spread_above_p75 = _spread_quality(row)
    hour = int(row.get("hour_utc", pd.Timestamp(frame.index[idx]).hour))
    session_q = _session_quality(hour)

    atr_band_ok = bool(
        np.isfinite(atr_pct) and ATR_MARKET_OK_MIN <= atr_pct <= ATR_MARKET_OK_MAX
    )
    market_ok = atr_band_ok and not spread_above_p75

    return VolContext(
        market_ok=market_ok,
        expansion_strength=_expansion_strength(atr_pct),
        compression_strength=_compression_strength(atr_pct),
        session_quality=session_q,
        atr_percentile=atr_pct,
        spread_quality=spread_q,
    )


def evaluate_vol_context_df(df: pd.DataFrame, idx: int) -> VolContext:
    """Evaluate from raw OHLCV (prepares frame internally, no look-ahead)."""
    if df is None or df.empty or idx < 0:
        return evaluate_vol_context(pd.DataFrame(), -1)
    window = df.iloc[: idx + 1].copy()
    frame = prepare_frame(window)
    if frame.empty:
        return evaluate_vol_context(pd.DataFrame(), -1)
    local_idx = len(frame) - 1
    return evaluate_vol_context(frame, local_idx)


def build_context_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Attach vol context columns to a prepared frame (research helper)."""
    base = _prepare_frame_round2(candles) if "atr_pct" not in candles.columns else candles.copy()
    rows: list[dict[str, Any]] = []
    for idx in range(len(base)):
        ctx = evaluate_vol_context(base, idx)
        rows.append(ctx.to_dict())
    ctx_df = pd.DataFrame(rows, index=base.index)
    return base.join(ctx_df, rsuffix="_ctx")
