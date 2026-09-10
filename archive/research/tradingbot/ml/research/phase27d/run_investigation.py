"""Phase 27D — full 30-day production replay after cache fix (READ ONLY)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase22c.hold_chain import get_hold_chain, reset_hold_chain
from tradingbot.ml.research.phase25b.unified_pipeline_replay import run_unified_pipeline_replay
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27d.metrics import (
    build_cache_statistics,
    build_engine_statistics,
    build_hold_funnel,
    build_journal_statistics,
    build_performance_statistics,
    build_pipeline_statistics,
    build_profitability_report,
    build_regime_statistics,
    build_risk_analysis,
    build_signal_statistics,
    build_trading_statistics,
    determine_verdict,
)
from tradingbot.ml.research.phase27a.metrics import build_latency_analysis
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = PHASE_DIR / "_cache"
REPLAY_DAYS = 30
WARMUP_BARS = 300
STRIDE = 1

DELIVERABLES = [
    "trading_statistics.json",
    "performance_statistics.json",
    "profitability.json",
    "risk_statistics.json",
    "signal_statistics.json",
    "engine_statistics.json",
    "regime_statistics.json",
    "journal_statistics.json",
    "pipeline_statistics.json",
    "hold_funnel.json",
    "latency_statistics.json",
    "cache_statistics.json",
    "final_report.json",
]


def _ts_iso(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return str(obj)
    return obj


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def run_phase27d(*, base_dir: str | Path | None = None, use_cache: bool = True) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    symbol = "XAUUSD"
    timeframe = "M5"

    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"
    os.environ["TRADINGBOT_PAPER"] = "1"

    candles_raw = CandleStore(root).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        raise RuntimeError("CandleStore unavailable for XAUUSD M5")

    window = prepare_calibration_candles(candles_raw, days=REPLAY_DAYS)
    window = normalize_candles_for_builder(window)
    if len(window) < WARMUP_BARS + 10:
        raise RuntimeError(f"Insufficient candles: {len(window)}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_records = CACHE_DIR / "replay_records.json"
    cache_meta = CACHE_DIR / "replay_meta.json"
    cache_hold = CACHE_DIR / "hold_chain.json"

    reset_hold_chain()
    t0 = time.perf_counter()
    if use_cache and cache_records.is_file() and cache_meta.is_file():
        records = json.loads(cache_records.read_text(encoding="utf-8"))
        replay_meta = json.loads(cache_meta.read_text(encoding="utf-8"))
        hold_chain = json.loads(cache_hold.read_text(encoding="utf-8")) if cache_hold.is_file() else {}
        elapsed = float(replay_meta.get("elapsed_sec") or 0)
        print(f"[phase27d] loaded cached replay ({len(records)} records)")
    else:
        print("[phase27d] running fresh 30-day production replay (post cache fix)...")
        records, replay_meta = run_unified_pipeline_replay(
            base_dir=str(root),
            symbol=symbol,
            timeframe=timeframe,
            days=REPLAY_DAYS,
            tail_only=None,
            stride=STRIDE,
            warmup_bars=WARMUP_BARS,
            use_forming_bar_adapter=True,
        )
        elapsed = round(time.perf_counter() - t0, 2)
        hold_chain = get_hold_chain().snapshot()
        replay_meta["elapsed_sec"] = elapsed
        replay_meta["phase27c_cache_fix"] = True
        replay_meta["phase27a_cache_invalidated"] = True
        cache_records.write_text(json.dumps(_json_safe(records)), encoding="utf-8")
        cache_meta.write_text(json.dumps(_json_safe(replay_meta)), encoding="utf-8")
        cache_hold.write_text(json.dumps(_json_safe(hold_chain)), encoding="utf-8")
        print(f"[phase27d] replay complete in {elapsed}s — {len(records)} bars")

    trades = build_completed_trades(records, window, symbol=symbol)
    profitability = build_profitability_report(trades)
    trading = build_trading_statistics(trades, records, replay_days=REPLAY_DAYS)
    performance = build_performance_statistics(trades, profitability, replay_days=REPLAY_DAYS)
    risk = build_risk_analysis(trades, records)
    signals = build_signal_statistics(records)
    engines = build_engine_statistics(trades, records)
    regimes = build_regime_statistics(trades, records)
    journal = build_journal_statistics(trades, records)
    pipeline = build_pipeline_statistics(records, replay_meta, hold_chain)
    hold_funnel = build_hold_funnel(records, hold_chain)
    latency = build_latency_analysis(records)
    cache = build_cache_statistics(records)

    verdict, blockers = determine_verdict(
        trades=trades,
        pipeline=pipeline,
        journal=journal,
        cache=cache,
        hold_chain=hold_chain,
    )

    window_meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "replay_days": REPLAY_DAYS,
        "warmup_bars": WARMUP_BARS,
        "stride": STRIDE,
        "window_bars": len(window),
        "window_start": _ts_iso(window.index.min()),
        "window_end": _ts_iso(window.index.max()),
        "pipeline": "phase25b.run_unified_pipeline_replay",
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "post_phase27c_cache_fix": True,
    }

    outputs = {
        "trading_statistics.json": {**trading, "generated_utc": ts, **window_meta},
        "performance_statistics.json": {**performance, "generated_utc": ts},
        "profitability.json": {**profitability, "generated_utc": ts},
        "risk_statistics.json": {**risk, "generated_utc": ts},
        "signal_statistics.json": {**signals, "generated_utc": ts},
        "engine_statistics.json": {**engines, "generated_utc": ts},
        "regime_statistics.json": {**regimes, "generated_utc": ts},
        "journal_statistics.json": {**journal, "generated_utc": ts},
        "pipeline_statistics.json": {**pipeline, "generated_utc": ts, **window_meta},
        "hold_funnel.json": {**hold_funnel, "generated_utc": ts},
        "latency_statistics.json": {**latency, "generated_utc": ts},
        "cache_statistics.json": {**cache, "generated_utc": ts},
        "final_report.json": {
            "phase": "27D",
            "generated_utc": ts,
            "verdict": verdict,
            "audit_mode": "READ_ONLY",
            "production_modified": False,
            "blockers": blockers,
            "replay_config": window_meta,
            "replay_meta": replay_meta,
            "completed_trades": len(trades),
            "bars_evaluated": replay_meta.get("bars_evaluated", len(records)),
            "hold_chain": hold_chain,
            "cache_uniqueness_pct": cache.get("prediction_uniqueness_pct"),
            "ml_signals_emitted": pipeline.get("ml_signals_emitted"),
            "profit_factor": profitability.get("profit_factor"),
            "expectancy": profitability.get("expectancy"),
            "summary": (
                f"Post-27C 30-day replay: {len(trades)} completed trades from "
                f"{replay_meta.get('bars_evaluated', len(records))} bars. "
                f"ML signals={pipeline.get('ml_signals_emitted')} "
                f"cache_uniqueness={cache.get('prediction_uniqueness_pct')}% "
                f"PF={profitability.get('profit_factor')} verdict={verdict}."
            ),
        },
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return outputs["final_report.json"]


def main() -> int:
    use_cache = "--no-cache" not in sys.argv
    report = run_phase27d(use_cache=use_cache)
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "READY_FOR_PAPER" else 1


if __name__ == "__main__":
    raise SystemExit(main())
