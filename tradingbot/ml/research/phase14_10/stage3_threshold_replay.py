"""Phase 14.10 Stage 3 — per-year threshold replay (no retrain / no full rebuild)."""

from __future__ import annotations

import gc
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.validation import load_production_engines, validate_artifacts_unchanged
from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_10.config import EXPECTED_FINGERPRINT, MIN_YEAR_BARS, THRESHOLD_GRID
from tradingbot.ml.research.phase14_10.stage1_yearly_statistics import (
    _bootstrap_calibration_year,
    load_year_candles,
    load_year_dataset,
    stage1_output_path,
)
from tradingbot.ml.research.phase14_10.config import phase14_10_reports_dir
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


def stage3_output_path(base_dir: str | Path | None = None) -> Path:
    return phase14_10_reports_dir(base_dir) / "threshold_per_year.json"


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _passes_threshold(record: dict[str, Any], threshold: float) -> bool:
    if record.get("raw_signal") not in ("BUY", "SELL"):
        return False
    if float(record.get("confidence", 0)) < threshold:
        return False
    if record.get("block_reason") in ("risk", "quality", "hold_action"):
        return False
    return True


def _metrics_at_threshold(
    records: list[dict[str, Any]],
    threshold: float,
    *,
    stride: int,
) -> dict[str, Any]:
    accepted = [r for r in records if _passes_threshold(r, threshold)]
    m = trade_metrics_from_records(accepted)
    conf = [float(r["confidence"]) for r in accepted if r.get("confidence") is not None]
    return {
        "threshold": threshold,
        "trades": m["trades"],
        "effective_trades_est": int(m["trades"] * max(1, stride)),
        "profit_factor": m["profit_factor"],
        "expectancy": m["expectancy"],
        "win_rate": m["win_rate"],
        "avg_confidence": round(sum(conf) / len(conf), 4) if conf else 0.0,
    }


def _load_stage1(base_dir: str | Path | None, input_path: str | Path | None) -> dict[str, Any]:
    path = Path(input_path) if input_path else stage1_output_path(base_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Stage 1 output not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_stage3_threshold_replay(
    *,
    base_dir: str | Path | None = None,
    stage1_path: str | Path | None = None,
    thresholds: tuple[float, ...] | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or THRESHOLD_GRID
    replay_floor = min(thresholds)

    stage1 = _load_stage1(base_dir, stage1_path)
    symbol = str(stage1.get("symbol", "XAUUSD"))
    timeframe = str(stage1.get("timeframe", "M5"))
    seed = int(stage1.get("seed", 42))
    stride = int(stage1.get("stride", 5))

    years = tuple(
        int(y)
        for y, v in sorted(stage1.get("per_year", {}).items())
        if not v.get("skipped")
    )
    if not years:
        raise ValueError("No active years in yearly_statistics.json")

    store = DatasetStore(base_dir)
    fp_before = dataset_content_fingerprint(store.load_v2(symbol, timeframe))
    candle_path = CandleStore(base_dir).resolve_path(symbol, timeframe)
    dataset_path = store.resolve_v2_path(symbol, timeframe)

    bootstrap_year = _bootstrap_calibration_year(years)
    boot_candles = load_year_candles(candle_path, bootstrap_year)
    boot_dataset = load_year_dataset(dataset_path, bootstrap_year)
    if boot_candles.empty or len(boot_candles) < MIN_YEAR_BARS:
        raise ValueError(f"Bootstrap year {bootstrap_year} has insufficient bars")

    range_engine, trend_engine = load_production_engines(boot_candles, symbol=symbol, seed=seed)
    cal_method, _ = load_recovered_calibration(
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
    del boot_candles, boot_dataset
    gc.collect()

    out_path = stage3_output_path(base_dir)
    payload: dict[str, Any] = {
        "phase": "14.10",
        "stage": 3,
        "description": "Per-year threshold replay from Stage 1 router config",
        "source": str(stage1_path or stage1_output_path(base_dir)),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "stride": stride,
        "threshold_grid": list(thresholds),
        "replay_floor_threshold": replay_floor,
        "method": "single_pass_replay",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "per_year": {},
    }
    _write_payload(out_path, payload)

    for year in years:
        year_candles = load_year_candles(candle_path, year)
        year_dataset = load_year_dataset(dataset_path, year)

        stage1_year = stage1.get("per_year", {}).get(str(year), {})
        if year_candles.empty or len(year_candles) < MIN_YEAR_BARS or stage1_year.get("skipped"):
            payload["per_year"][str(year)] = {"year": year, "skipped": True}
        else:
            records = run_adaptive_router_pipeline(
                year_candles,
                year_dataset,
                cal_method,
                confidence_threshold=replay_floor,
                symbol=symbol,
                timeframe=timeframe,
                seed=seed,
                stride=stride,
                range_engine=range_engine,
                trend_engine=trend_engine,
            )
            threshold_results = {
                str(th): _metrics_at_threshold(records, th, stride=stride)
                for th in thresholds
            }
            best = max(threshold_results.values(), key=lambda x: x["profit_factor"])
            pfs = [v["profit_factor"] for v in threshold_results.values()]
            payload["per_year"][str(year)] = {
                "year": year,
                "skipped": False,
                "bars": len(year_candles),
                "thresholds": threshold_results,
                "best_threshold_by_pf": best["threshold"],
                "best_pf": best["profit_factor"],
                "threshold_spread_pf": round(max(pfs) - min(pfs), 4),
                "stage1_pf_at_030": stage1_year.get("profit_factor"),
            }
            del records

        del year_candles, year_dataset
        gc.collect()

        payload["last_completed_year"] = year
        payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_payload(out_path, payload)

    fp_after = dataset_content_fingerprint(store.load_v2(symbol, timeframe))
    artifacts = validate_artifacts_unchanged()

    active = [v for v in payload["per_year"].values() if not v.get("skipped")]
    payload["optimal_threshold_per_year"] = {
        str(v["year"]): v["best_threshold_by_pf"] for v in active
    }
    payload["mean_threshold_spread_pf"] = round(
        sum(v["threshold_spread_pf"] for v in active) / len(active), 4
    ) if active else 0.0
    payload["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["dataset_fingerprint"] = fp_before
    payload["expected_fingerprint"] = EXPECTED_FINGERPRINT
    payload["fingerprint_unchanged"] = fp_before == fp_after
    payload["artifact_checksums"] = artifacts
    payload["output_path"] = str(out_path)
    _write_payload(out_path, payload)
    return payload
