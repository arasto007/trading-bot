"""Phase 118 - tick forensic validation of operator XAUUSD_i export.

RESEARCH ONLY. Validates and normalizes the Phase 117 operator MT5 tick export.
Does not connect to MT5, read .env, place orders, modify production, implement an
exit spec, or start Phase 119. Preserves the raw export byte-identical.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    _git_head,
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import BAR_MINUTES
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase114_non_ohlc_acquisition_contract import (
    CANONICAL_SYMBOL,
    LOGICAL_SYMBOL,
    TZ,
)
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    CHRONOLOGY_CLASSES,
    EXPECTED_JSONL_SHA256,
    N_AMBIGUOUS_394,
    N_EVENTS,
    PHASE40_TS,
    _event_in_range,
    _lifecycle_in_range,
    _load_events,
    _ticks_cover_state,
    asof_tick_index,
    classify_intrabar_order,
    derive_spread,
    enforce_utc,
    file_sha256,
    gap_statistics,
    iso_z,
    trading_day_counts,
    validate_tick_frame,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS
from tradingbot.backtest.phase117_operator_source_resolution import RAW_DROP_REL

PHASE = "118"
PHASE118_JSON = "logs/phase118_tick_forensic_validation.json"
PHASE118_MD = "docs/PHASE118_TICK_FORENSIC_VALIDATION.md"
NORMALIZED_REL = "data/research/non_ohlc/normalized/phase118"
DERIVED_REL = "data/research/non_ohlc/derived/phase118"
NORMALIZATION_VERSION = "phase118-v1"
EXPECTED_RAW_SHA256 = "13e7512052242a903947837ee60d1a87a44f9aada4c4d7a6bd4fc2770f366d75"
EXPECTED_RAW_NAME = "XAUUSD_i_202607230101_202609072009.csv"
EXPECTED_RAW_SIZE = 454365643
CHUNKSIZE = 500_000
PHASE115_RESOLVED_AMBIGUOUS = 3
REJECT_SYMBOLS = frozenset({"XAUUSD", "GOLD", "GOLDUSD", "GOLD/USD", "XAU/USD"})
QUOTE_CARRY_FORWARD_NOTE = (
    "quote-state carry-forward from prior tick in same export"
    " — NOT synthetic/interpolated tick invention"
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PHASE118_STATUS",
    "RAW_FILE_PRESENT",
    "DATA_ACQUIRED",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def discover_raw_file(root: Path) -> Path | None:
    """Locate the Phase 117 operator export. Prefer the known filename."""
    drop = Path(root) / RAW_DROP_REL
    if not drop.is_dir():
        return None
    preferred = drop / EXPECTED_RAW_NAME
    if preferred.is_file():
        return preferred
    cands = sorted(
        p
        for p in drop.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".csv", ".tsv", ".txt"}
        and verify_xauusd_i(path=p.name)
    )
    return cands[0] if cands else None


def _strip_angle_headers(columns: list[Any]) -> list[str]:
    out = []
    for c in columns:
        s = str(c).strip()
        if s.startswith("<") and s.endswith(">"):
            s = s[1:-1]
        out.append(s.strip().lower())
    return out


def parse_mt5_datetime_utc(date_s: pd.Series, time_s: pd.Series) -> pd.Series:
    """Combine MT5 DATE+TIME into UTC timestamps.

    Documented convention: export wall-clock treated as UTC (end aligns with
    requested UTC window ACQ_END_ISO).
    """
    d = date_s.astype(str).str.strip().str.replace(".", "-", regex=False)
    t = time_s.astype(str).str.strip()
    return pd.to_datetime(d + " " + t, utc=True, errors="coerce")


def verify_raw_sha256(path: Path, expected: str = EXPECTED_RAW_SHA256) -> dict[str, Any]:
    """Hash BEFORE any normalize write. Does not modify the file."""
    sha = file_sha256(path)
    return {
        "path": str(path),
        "sha256": sha,
        "expected": expected,
        "match": sha == expected,
        "size_bytes": int(path.stat().st_size) if path.is_file() else None,
    }
