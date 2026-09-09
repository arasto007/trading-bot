"""Historical M5 bid/ask tape contract — no current-tick / OHLC / proxy substitution."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from tradingbot.backtest.cost_model import frame_has_historical_bid_ask
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS

CANONICAL_SYMBOL = "XAUUSD_i"
CANONICAL_TIMEFRAME = "M5"
REQUIRED_PROVENANCE = (
    "symbol",
    "timeframe",
    "source",
    "collection_method",
    "row_count",
    "time_range",
    "fingerprint",
)

SUBSTITUTION_FORBIDDEN = (
    "current_bid_ask_tick",
    "ohlc_spread",
    "proxy_spread",
)


class HistoricalBidAskError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _col(df: pd.DataFrame, name: str) -> str | None:
    for c in df.columns:
        if str(c).lower() == name.lower():
            return str(c)
    return None


def tape_fingerprint(df: pd.DataFrame) -> str:
    bid_c = _col(df, "bid")
    ask_c = _col(df, "ask")
    if bid_c is None or ask_c is None or not isinstance(df.index, pd.DatetimeIndex):
        payload = str(len(df)).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    idx = pd.to_datetime(df.index, utc=True).astype("int64")
    bid = pd.to_numeric(df[bid_c], errors="coerce").fillna(0.0)
    ask = pd.to_numeric(df[ask_c], errors="coerce").fillna(0.0)
    raw = pd.DataFrame({"t": idx.to_numpy(), "b": bid.to_numpy(), "a": ask.to_numpy()}).to_csv(
        index=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def provenance_complete(meta: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = [k for k in REQUIRED_PROVENANCE if not meta.get(k)]
    return (not missing, missing)


def credentials_contaminated(meta: dict[str, Any]) -> bool:
    blob = json.dumps(meta, default=str).lower()
    for key in FORBIDDEN_OUTPUT_KEYS:
        if f'"{key}"' in blob or f"'{key}'" in blob:
            return True
    return False


def current_tick_is_not_historical(meta: dict[str, Any]) -> bool:
    method = str(meta.get("collection_method") or "").lower()
    source = str(meta.get("source") or "").lower()
    if "symbol_info_tick" in method or "live_tick" in source or "current_quote" in source:
        return False
    return True


def validate_historical_m5_tape(
    df: pd.DataFrame | None,
    *,
    symbol: str,
    timeframe: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if df is None or df.empty:
        errors.append("empty_frame")
    if symbol != CANONICAL_SYMBOL:
        errors.append(f"wrong_symbol:{symbol}")
    if str(timeframe).upper() not in ("M5", "5M", "5MIN"):
        errors.append(f"wrong_timeframe:{timeframe}")
    if df is not None and not df.empty:
        if not isinstance(df.index, pd.DatetimeIndex):
            errors.append("index_not_datetime")
        else:
            if not df.index.is_monotonic_increasing:
                errors.append("timestamps_not_monotonic")
            if int(df.index.duplicated().sum()) > 0:
                errors.append("duplicate_timestamps")
        if not frame_has_historical_bid_ask(df):
            errors.append("missing_or_invalid_bid_ask")
        bid_c = _col(df, "bid")
        ask_c = _col(df, "ask")
        if bid_c and ask_c:
            bid = pd.to_numeric(df[bid_c], errors="coerce")
            ask = pd.to_numeric(df[ask_c], errors="coerce")
            if bid.isna().any() or ask.isna().any():
                errors.append("malformed_bid_ask")
            if ((ask - bid) < 0).any():
                errors.append("malformed_bid_ask_negative_spread")
    complete, missing = provenance_complete(provenance)
    if not complete:
        errors.append(f"provenance_incomplete:{','.join(missing)}")
    if credentials_contaminated(provenance):
        errors.append("credential_contamination")
    if not current_tick_is_not_historical(provenance):
        errors.append("current_tick_substituted_for_historical")
    for forbidden in SUBSTITUTION_FORBIDDEN:
        if provenance.get(forbidden):
            errors.append(f"substitution_forbidden:{forbidden}")
    return {
        "ok": not errors,
        "errors": errors,
        "symbol_ok": symbol == CANONICAL_SYMBOL,
        "timeframe_ok": str(timeframe).upper() in ("M5", "5M", "5MIN"),
        "has_historical_bid_ask": bool(df is not None and frame_has_historical_bid_ask(df)),
        "provenance_complete": complete,
        "credentials_contaminated": credentials_contaminated(provenance),
    }
