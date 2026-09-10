"""L1 — build v8 enriched dataset from fullest candles + v7 features (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles

ROOT = Path(__file__).resolve().parents[4]
SPEC_PATH = Path(__file__).resolve().parent / "v8_dataset_spec.json"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_partial.parquet"
OUT_DIR = Path(__file__).resolve().parent / "artifacts"
OUT_PARQUET = OUT_DIR / "dataset_v8_enriched.parquet"
REPORT_PATH = ROOT / "live_l1_v8_build_report.json"

V7_FEATURE_COLS = [
    "ema50_slope",
    "ema200_distance",
    "price_above_ema200",
    "trend_strength",
    "ema_cross_state",
    "rsi_14",
    "roc_10",
    "macd_histogram",
    "momentum_5",
    "stoch_k",
    "atr_14",
    "atr_percentile",
    "realized_vol_20",
    "range_pct",
    "volatility_regime",
    "body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "engulfing_flag",
    "pin_bar_flag",
    "candle_direction",
    "bos_state",
    "choch_state",
    "liquidity_sweep",
    "fvg_presence",
    "order_block_distance",
    "bar_spread_pct",
    "tick_volume_proxy",
    "ml_confidence",
    "ml_probability",
    "regime",
    "label_v3",
    "label",
    "stop_loss_v3",
    "take_profit_v3",
    "direction",
    "event_type",
]


def _load_spec() -> dict[str, Any]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _session_flags(hours: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_london": ((hours >= 7) & (hours < 12)).astype(np.int8),
            "session_new_york": ((hours >= 13) & (hours < 17)).astype(np.int8),
            "session_asia": ((hours >= 0) & (hours < 7)).astype(np.int8),
            "session_off_hours": (
                ~((hours >= 7) & (hours < 12))
                & ~((hours >= 13) & (hours < 17))
                & ~((hours >= 0) & (hours < 7))
            ).astype(np.int8),
        }
    )


def _session_label(hour: int) -> str:
    if 7 <= hour < 12:
        return "london"
    if 13 <= hour < 17:
        return "new_york"
    if 0 <= hour < 7:
        return "asia"
    return "off_hours"


def build_v8_dataset(
    *,
    year_start: int = 2021,
    year_end: int = 2026,
    include_v7_merge: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    spec = _load_spec()
    candles = resolve_fullest_candles(spec.get("symbol", "XAUUSD"), spec.get("timeframe", "M5"))
    if candles is None or candles.empty:
        raise RuntimeError("fullest candle source missing")

    c = candles.copy()
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    c = c[(c.index.year >= year_start) & (c.index.year <= year_end)]
    if c.empty:
        raise RuntimeError(f"no candles in {year_start}-{year_end}")

    o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
    vol = c["volume"] if "volume" in c.columns else pd.Series(1.0, index=c.index)

    df = pd.DataFrame(index=c.index)
    df["timestamp"] = df.index
    df["open"] = o.values
    df["high"] = h.values
    df["low"] = l.values
    df["close"] = cl.values
    df["volume"] = vol.values
    df["bar_index"] = np.arange(len(df), dtype=np.int64)

    df["hour_of_day"] = df.index.hour.astype(np.int8)
    df["day_of_week"] = df.index.dayofweek.astype(np.int8)
    df["year"] = df.index.year.astype(np.int16)

    sessions = _session_flags(df["hour_of_day"])
    df = pd.concat([df, sessions], axis=1)
    df["session"] = df["hour_of_day"].map(_session_label)

    atr14 = _atr(h, l, cl, 14)
    df["atr_14_computed"] = atr14.values
    df["atr_percentile"] = atr14.rolling(500, min_periods=100).rank(pct=True).values

    if "spread_pips" in c.columns:
        df["spread_pips"] = c["spread_pips"].values
        df["spread_proxy"] = c["spread_pips"].values
    else:
        df["spread_proxy"] = ((h - l) / cl.replace(0, np.nan) * 10000.0).values
        df["spread_pips"] = np.nan

    df["spread_pips_source"] = "broker" if "spread_pips" in c.columns else "range_proxy"
    df["ema200_computed"] = _ema(cl, 200).values
    df["rsi_14_computed"] = _rsi(cl, 14).values
    df["ema200_distance_computed"] = ((cl - df["ema200_computed"]) / cl.replace(0, np.nan)).values

    v7_rows = 0
    v7_cols_merged: list[str] = []
    if include_v7_merge and V7_PATH.is_file():
        v7 = pd.read_parquet(V7_PATH)
        v7["timestamp"] = pd.to_datetime(v7["timestamp"], utc=True)
        merge_cols = ["timestamp"] + [c for c in V7_FEATURE_COLS if c in v7.columns]
        v7_sub = v7[merge_cols].drop_duplicates(subset=["timestamp"], keep="last")
        df = df.merge(v7_sub, on="timestamp", how="left", suffixes=("", "_v7"))
        v7_rows = int(df["label_v3"].notna().sum()) if "label_v3" in df.columns else 0
        v7_cols_merged = [c for c in V7_FEATURE_COLS if c in df.columns]

    return df, {
        "spec_version": spec.get("version"),
        "year_range": [year_start, year_end],
        "rows": len(df),
        "columns": len(df.columns),
        "v7_merge_rows": v7_rows,
        "v7_cols_merged": v7_cols_merged,
        "start": str(df["timestamp"].min()),
        "end": str(df["timestamp"].max()),
    }


def _validation_report(df: pd.DataFrame, build_meta: dict[str, Any]) -> dict[str, Any]:
    year_counts = df.groupby("year").size().astype(int).to_dict()
    year_counts = {str(k): int(v) for k, v in sorted(year_counts.items())}

    null_checks: dict[str, Any] = {}
    critical = ["open", "high", "low", "close", "hour_of_day", "atr_percentile", "spread_proxy", "session"]
    for col in critical:
        if col in df.columns:
            null_checks[col] = {
                "null_count": int(df[col].isna().sum()),
                "null_pct": round(float(df[col].isna().mean() * 100), 4),
            }

    spread_present = bool(df["spread_pips"].notna().any()) if "spread_pips" in df.columns else False
    min_rows_per_year = min(year_counts.values()) if year_counts else 0
    years_covered = len(year_counts)

    gates = {
        "min_history_years": bool(years_covered >= 5),
        "spread_present_or_proxy": True,
        "sessions_tagged": bool("session" in df.columns and df["session"].notna().all()),
        "min_rows_per_year_30k": bool(min_rows_per_year >= 30000),
    }

    return {
        "phase": "L1",
        "title": "v8 Dataset Build",
        "title_fa": "ساخت دیتاست v8 غنی‌شده",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "V8_BUILD_COMPLETE" if all(gates.values()) else "V8_BUILD_PARTIAL",
        "research_only": True,
        "build": build_meta,
        "validation": {
            "row_count": len(df),
            "years_covered": years_covered,
            "year_distribution": year_counts,
            "null_checks": null_checks,
            "spread_broker_present": spread_present,
            "spread_proxy_used": build_meta.get("spread_pips_source", "range_proxy") == "range_proxy",
        },
        "gates": gates,
        "output_parquet": str(OUT_PARQUET.relative_to(ROOT)),
        "output_parquet_absolute": str(OUT_PARQUET),
    }


def write_outputs(df: pd.DataFrame, report: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> dict[str, Any]:
    print("L1: building v8 enriched dataset 2021-2026 ...", flush=True)
    df, build_meta = build_v8_dataset()
    report = _validation_report(df, build_meta)
    write_outputs(df, report)
    print(
        f"L1 done: rows={report['validation']['row_count']} verdict={report['verdict']}",
        flush=True,
    )
    print(f"Parquet: {OUT_PARQUET}", flush=True)
    print(f"Report: {REPORT_PATH}", flush=True)
    return report


if __name__ == "__main__":
    main()
