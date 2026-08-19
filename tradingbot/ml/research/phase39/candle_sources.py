"""Phase 39 — candle source audit and fullest-history resolver (research only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config, project_root
from tradingbot.ml.data.paths import candle_path, legacy_candle_path, normalize_ml_base_dir


@dataclass(frozen=True)
class CandleSourceInfo:
    path: str
    rows: int
    start: str
    end: str
    source_kind: str


def _read_range(path: Path) -> CandleSourceInfo | None:
    if not path.is_file():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if df.empty:
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            idx = pd.to_datetime(df["timestamp"], utc=True)
        elif "time" in df.columns:
            idx = pd.to_datetime(df["time"], utc=True)
        else:
            return None
    else:
        idx = pd.to_datetime(df.index, utc=True)
    return CandleSourceInfo(
        path=str(path),
        rows=len(df),
        start=str(idx.min()),
        end=str(idx.max()),
        source_kind=path.parent.parent.name,
    )


def canonical_raw_candle_path(symbol: str = "XAUUSD", timeframe: str = "M5") -> Path:
    """Canonical refreshed candle store (data/ml/raw/candles)."""
    tf = timeframe.lower().replace("5m", "m5").replace("15m", "m15").replace("4h", "h4").replace("1m", "m1")
    return project_root() / "data" / "ml" / "raw" / "candles" / tf / f"{symbol.upper()}_{tf}.parquet"


def discover_candle_sources(symbol: str = "XAUUSD", timeframe: str = "M5") -> list[CandleSourceInfo]:
    """Enumerate known candle parquet locations without mutating storage."""
    base_dir = load_legacy_config().get("BASE_DIR")
    norm = normalize_ml_base_dir(base_dir)
    canonical = canonical_raw_candle_path(symbol, timeframe)
    candidates = [
        canonical,
        candle_path(symbol, timeframe, None),
        candle_path(symbol, timeframe, norm),
        candle_path(symbol, timeframe, base_dir),
        legacy_candle_path(symbol, timeframe, None),
        legacy_candle_path(symbol, timeframe, norm),
        legacy_candle_path(symbol, timeframe, base_dir),
        project_root() / "ml" / "raw" / "candles" / "m5" / f"{symbol.upper()}_m5.parquet",
    ]
    seen: set[str] = set()
    out: list[CandleSourceInfo] = []
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        info = _read_range(path)
        if info is not None:
            out.append(info)
    # Prefer most recent end timestamp, then row count (fixes stale truncated ml/ paths).
    return sorted(out, key=lambda x: (x.end, x.rows), reverse=True)


def resolve_fullest_candles(symbol: str = "XAUUSD", timeframe: str = "M5") -> pd.DataFrame | None:
    """Load the candle file with the freshest end date and fullest history (read-only)."""
    sources = discover_candle_sources(symbol, timeframe)
    if not sources:
        return None
    canonical = canonical_raw_candle_path(symbol, timeframe)
    canonical_info = next((s for s in sources if Path(s.path).resolve() == canonical.resolve()), None)
    best = sources[0]
    if canonical_info is not None and canonical_info.end >= best.end:
        best = canonical_info
    df = pd.read_parquet(best.path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        elif "time" in df.columns:
            df = df.set_index("time")
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def audit_report(symbol: str = "XAUUSD", timeframe: str = "M5") -> dict[str, Any]:
    sources = discover_candle_sources(symbol, timeframe)
    truncated = None
    full = sources[0] if sources else None
    if len(sources) > 1:
        truncated = sources[-1]
    coverage_gain_pct = 0.0
    if full and truncated and truncated.rows > 0:
        coverage_gain_pct = round((full.rows - truncated.rows) / truncated.rows * 100, 2)

    root_cause = "NONE"
    if full and truncated and full.rows > truncated.rows * 2:
        root_cause = "BASE_DIR_POINTS_TO_TRUNCATED_ML_PATH"

    canonical = canonical_raw_candle_path(symbol, timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "canonical_path": str(canonical),
        "sources_found": len(sources),
        "fullest_source": full.__dict__ if full else None,
        "truncated_source": truncated.__dict__ if truncated else None,
        "row_gain_pct": coverage_gain_pct,
        "root_cause": root_cause,
        "recommendation": "USE_CANONICAL_RAW_CANDLE_VIA_resolve_fullest_candles",
        "all_sources": [s.__dict__ for s in sources],
    }
