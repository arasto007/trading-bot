"""Per-feature dtype, nullable policy, and validation range specs."""

from __future__ import annotations

from typing import Any

# dtype: float | int | binary
# nullable_policy: zero_fill | forbidden | allowed
# Optional: min, max, allowed_values

FEATURE_ENRICHMENT: dict[str, dict[str, Any]] = {
    # trend
    "ema50_slope": {"dtype": "float", "nullable_policy": "zero_fill"},
    "ema200_distance": {"dtype": "float", "nullable_policy": "zero_fill"},
    "price_above_ema200": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "trend_strength": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 100},
    "ema_cross_state": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    # momentum
    "rsi_14": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 100},
    "roc_10": {"dtype": "float", "nullable_policy": "zero_fill"},
    "macd_histogram": {"dtype": "float", "nullable_policy": "zero_fill"},
    "momentum_5": {"dtype": "float", "nullable_policy": "zero_fill"},
    "stoch_k": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 100},
    # volatility
    "atr_14": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0},
    "atr_percentile": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 100},
    "realized_vol_20": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0},
    "range_pct": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0},
    "volatility_regime": {"dtype": "float", "nullable_policy": "zero_fill", "allowed_values": [0, 0.5, 1]},
    # price action
    "body_ratio": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 1},
    "upper_wick_ratio": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 1},
    "lower_wick_ratio": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 1},
    "engulfing_flag": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "pin_bar_flag": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "candle_direction": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 1]},
    # smc
    "bos_state": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "choch_state": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "liquidity_sweep": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "fvg_presence": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "order_block_distance": {"dtype": "float", "nullable_policy": "zero_fill"},
    "premium_discount_location": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "structure_distance": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0},
    # htf context
    "h4_trend_bias": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "h4_structure_direction": {"dtype": "int", "nullable_policy": "zero_fill", "allowed_values": [-1, 0, 1]},
    "m15_market_state": {"dtype": "float", "nullable_policy": "zero_fill", "min": -1, "max": 1},
    "m5_entry_context": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 1},
    # session
    "session_asia": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "session_london": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "session_ny": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "session_off": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "in_london_kill": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "in_ny_kill": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "is_friday": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "hour_utc_norm": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0, "max": 1},
    # microstructure
    "spread_pips": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0},
    "spread_zscore": {"dtype": "float", "nullable_policy": "zero_fill"},
    "spread_spike": {"dtype": "binary", "nullable_policy": "zero_fill", "allowed_values": [0, 1]},
    "tick_volume_proxy": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0},
    "bar_spread_pct": {"dtype": "float", "nullable_policy": "zero_fill", "min": 0},
}


def enrich_definition(defn_dict: dict[str, Any]) -> dict[str, Any]:
    name = defn_dict.get("name", "")
    extra = FEATURE_ENRICHMENT.get(name, {})
    out = dict(defn_dict)
    out.setdefault("dtype", extra.get("dtype", "float"))
    out.setdefault("nullable_policy", extra.get("nullable_policy", "zero_fill"))
    if "min" in extra:
        out["min"] = extra["min"]
    if "max" in extra:
        out["max"] = extra["max"]
    if "allowed_values" in extra:
        out["allowed_values"] = extra["allowed_values"]
    return out
