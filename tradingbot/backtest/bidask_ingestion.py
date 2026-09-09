"""Offline bid/ask parquet ingestion — no MT5, no synthetic market data."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from tradingbot.backtest.cost_model import SpreadMode, validate_dataset_spread
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    SidecarValidationError,
    save_dataset_metadata,
    validate_sidecar_against_parquet,
    validate_sidecar_no_credentials,
)


class BidAskIngestionError(Exception):
    """Bid/ask import rejected — fail closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


REQUIRED_OHLC = ("open", "high", "low", "close")
REQUIRED_BIDASK = ("bid", "ask")


def validate_bidask_frame(
    df: pd.DataFrame,
    *,
    expected_symbol: str,
    metadata: DatasetMetadata | None = None,
) -> tuple[bool, str]:
    """Validate imported frame has bid/ask with defensible spread — no synthetic fill."""
    if df is None or df.empty:
        return False, "empty_frame"
    cols = {str(c).lower() for c in df.columns}
    if not all(c in cols for c in REQUIRED_BIDASK):
        return False, "missing_bid_or_ask"
    if not all(c in cols for c in REQUIRED_OHLC):
        return False, "missing_ohlc_columns"

    spread = validate_dataset_spread(
        df,
        digits=metadata.digits if metadata else None,
        point=metadata.point if metadata else None,
    )
    if spread.spread_mode != SpreadMode.DATASET:
        return False, f"spread_not_dataset:{spread.spread_source}"
    if spread.errors:
        return False, spread.errors[0]

    if metadata is not None and metadata.dataset_symbol and metadata.dataset_symbol != expected_symbol:
        return False, f"symbol_mismatch:{metadata.dataset_symbol}!={expected_symbol}"

    return True, "ok"


def ingest_bidask_parquet(
    source_path: str | Path,
    target_path: str | Path,
    metadata: DatasetMetadata,
    *,
    copy: bool = True,
) -> Path:
    """
    Import externally collected bid/ask parquet with provenance sidecar.

    Does not connect to MT5. Does not modify source. Fails closed on validation errors.
    """
    src = Path(source_path)
    dst = Path(target_path)
    if not src.is_file():
        raise BidAskIngestionError("SOURCE_MISSING", f"source not found: {src}")

    if not validate_sidecar_no_credentials(metadata.to_dict()):
        raise SidecarValidationError("CREDENTIALS_IN_METADATA", "metadata contains forbidden credential fields")

    df = pd.read_parquet(src)
    ok, reason = validate_bidask_frame(
        df,
        expected_symbol=metadata.dataset_symbol,
        metadata=metadata,
    )
    if not ok:
        raise BidAskIngestionError("VALIDATION_FAILED", reason)

    ok_sidecar, sidecar_reason = validate_sidecar_against_parquet(metadata, df, src)
    if not ok_sidecar:
        raise SidecarValidationError("SIDECAR_PARQUET_MISMATCH", sidecar_reason)

    metadata.spread_mode = SpreadMode.DATASET.value
    if not metadata.spread_source:
        metadata.spread_source = "bid_ask_columns"
    metadata.historical_bid_ask_available = True

    dst.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        shutil.copy2(src, dst)
    else:
        df.to_parquet(dst, index=True)

    save_dataset_metadata(dst, metadata)
    return dst
