"""Phase 14.10 Stage 1 — fast per-year statistics (no MC / WF / threshold search)."""

from __future__ import annotations

import gc
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.validation import load_production_engines, validate_artifacts_unchanged
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_9.config import GRID_STRIDE as PHASE149_GRID_STRIDE
from tradingbot.ml.research.phase14_10.config import (
    EXPECTED_FINGERPRINT,
    MIN_YEAR_BARS,
    WF_YEARS,
    load_calibration_policy,
    phase14_10_reports_dir,
    regime_pct_from_records,
)
from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


def stage1_output_path(base_dir: str | Path | None = None) -> Path:
    return phase14_10_reports_dir(base_dir) / "yearly_statistics.json"


def _year_bounds(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    return start, end


def load_year_candles(path: Path, year: int) -> pd.DataFrame:
    start, end = _year_bounds(year)
    filters = [("time", ">=", start), ("time", "<=", end)]
    df = pd.read_parquet(path, filters=filters)
    if df.empty:
        return df
    if "time" in df.columns:
        df = df.set_index("time")
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def load_year_dataset(path: Path, year: int) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    start, end = _year_bounds(year)
    filters = [("timestamp", ">=", start), ("timestamp", "<=", end)]
    df = pd.read_parquet(path, filters=filters)
    if df.empty:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def _year_stats(records: list[dict[str, Any]], *, stride: int) -> dict[str, Any]:
    accepted = [r for r in records if r.get("allowed")]
    m = trade_metrics_from_records(accepted)
    conf = [float(r["confidence"]) for r in accepted if r.get("confidence") is not None]
    risk = [float(r["risk_percent"]) for r in accepted if r.get("risk_percent") is not None]
    quality = [float(r["quality_score"]) for r in accepted if r.get("quality_score") is not None]
    trend_trades = sum(1 for r in accepted if str(r.get("engine")) == "trend_rf_v40")
    range_trades = sum(1 for r in accepted if str(r.get("engine")) == "phase9_9")

    return {
        "trades": m["trades"],
        "effective_trades_est": int(m["trades"] * max(1, stride)),
        "profit_factor": m["profit_factor"],
        "expectancy": m["expectancy"],
        "win_rate": m["win_rate"],
        "avg_confidence": round(sum(conf) / len(conf), 4) if conf else 0.0,
        "avg_risk": round(sum(risk) / len(risk), 4) if risk else 0.0,
        "avg_quality": round(sum(quality) / len(quality), 4) if quality else 0.0,
        "regime_distribution": regime_pct_from_records(records),
        "trend_trades": trend_trades,
        "range_trades": range_trades,
    }


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _bootstrap_calibration_year(years: tuple[int, ...]) -> int:
    for preferred in (2024, 2023, 2025, 2022):
        if preferred in years:
            return preferred
    return years[0]


def run_stage1_yearly_statistics(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
    years: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    years = years or WF_YEARS
    stride = PHASE149_GRID_STRIDE
    out_path = stage1_output_path(base_dir)

    store = DatasetStore(base_dir)
    fp_before = dataset_content_fingerprint(store.load_v2(symbol, timeframe))

    candle_path = CandleStore(base_dir).resolve_path(symbol, timeframe)
    if not candle_path.is_file():
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")

    dataset_path = store.resolve_v2_path(symbol, timeframe)
    cal_policy = load_calibration_policy(base_dir)
    bootstrap_year = _bootstrap_calibration_year(years)

    boot_candles = load_year_candles(candle_path, bootstrap_year)
    boot_dataset = load_year_dataset(dataset_path, bootstrap_year)
    if boot_candles.empty or len(boot_candles) < MIN_YEAR_BARS:
        raise ValueError(f"Bootstrap year {bootstrap_year} has insufficient bars for calibration")

    range_engine, trend_engine = load_production_engines(boot_candles, symbol=symbol, seed=seed)
    cal_method, cal_meta = load_recovered_calibration(
        boot_candles,
        boot_dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
    )
    confidence_threshold = float(cal_meta.get("confidence_threshold", cal_policy["confidence_threshold"]))

    del boot_candles, boot_dataset
    gc.collect()

    payload: dict[str, Any] = {
        "phase": "14.10",
        "stage": 1,
        "description": "Fast annual statistics — Phase 14.9 adaptive router config",
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "stride": stride,
        "confidence_threshold": confidence_threshold,
        "calibration_method": cal_policy.get("calibration_method", "platt"),
        "router": "phase14_9_adaptive",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "per_year": {},
        "years": list(years),
    }
    _write_payload(out_path, payload)

    for year in years:
        year_candles = load_year_candles(candle_path, year)
        year_dataset = load_year_dataset(dataset_path, year)

        if year_candles.empty or len(year_candles) < MIN_YEAR_BARS:
            payload["per_year"][str(year)] = {
                "year": year,
                "skipped": True,
                "reason": "insufficient_bars",
            }
        else:
            records = run_adaptive_router_pipeline(
                year_candles,
                year_dataset,
                cal_method,
                confidence_threshold=confidence_threshold,
                symbol=symbol,
                timeframe=timeframe,
                seed=seed,
                stride=stride,
                range_engine=range_engine,
                trend_engine=trend_engine,
            )
            stats = _year_stats(records, stride=stride)
            payload["per_year"][str(year)] = {
                "year": year,
                "skipped": False,
                "bars": len(year_candles),
                **stats,
            }
            del records

        del year_candles, year_dataset
        gc.collect()

        payload["last_completed_year"] = year
        payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_payload(out_path, payload)

    fp_after = dataset_content_fingerprint(store.load_v2(symbol, timeframe))
    artifacts = validate_artifacts_unchanged()

    payload["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["dataset_fingerprint"] = fp_before
    payload["expected_fingerprint"] = EXPECTED_FINGERPRINT
    payload["fingerprint_unchanged"] = fp_before == fp_after
    payload["artifact_checksums"] = artifacts
    payload["active_years"] = sum(
        1 for v in payload["per_year"].values() if not v.get("skipped")
    )
    payload["output_path"] = str(out_path)
    _write_payload(out_path, payload)
    return payload
