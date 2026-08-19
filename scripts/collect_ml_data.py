#!/usr/bin/env python3
"""Collect ML training data — Phase 1 + Phase 8.0 historical collection."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.roles import (
    CONTEXT_TIMEFRAME,
    DATA_ONLY_TIMEFRAMES,
    ENTRY_TIMEFRAME,
    HIGHER_TIMEFRAME_BIAS,
    TRADING_TIMEFRAMES,
)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_timeframes(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [tf.strip().upper() for tf in value.split(",") if tf.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="ML data pipeline — Phase 1 + 8.0 historical collector")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--m1-bars", type=int, default=10_000)
    parser.add_argument("--tick-hours", type=int, default=24)
    parser.add_argument("--events-only", action="store_true", help="Skip MT5 fetch; extract events from cached candles")
    parser.add_argument("--report", action="store_true", help="Print data quality status report only")
    parser.add_argument("--features", action="store_true", help="Build Phase 2 features from cached candles")
    parser.add_argument("--dataset", action="store_true", help="Build Phase 3 labeled dataset from features + events")
    parser.add_argument("--historical", action="store_true", help="Phase 8.0 historical candle collection")
    parser.add_argument("--days", type=int, default=365, help="History depth in days (historical / incremental default)")
    parser.add_argument("--start-date", default=None, help="ISO start date UTC (historical)")
    parser.add_argument("--end-date", default=None, help="ISO end date UTC (historical, default now)")
    parser.add_argument(
        "--timeframes",
        default=None,
        help="Comma-separated TFs for historical collection (default M5,M15,H4)",
    )
    parser.add_argument("--incremental", action="store_true", help="Resume from metadata last_update_utc")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate stored raw candles against Phase 8 minimum bar gates",
    )
    parser.add_argument("--optimized", action="store_true", help="Phase 8.4 optimized historical collector")
    parser.add_argument("--workers", type=int, default=4, help="Parallel TF workers (optimized mode)")
    parser.add_argument("--resume", action="store_true", help="Resume optimized collection from state files")
    parser.add_argument(
        "--parallel-timeframes",
        action="store_true",
        help="Collect timeframes in parallel (optimized mode, default when --optimized)",
    )
    parser.add_argument(
        "--chunk-size",
        default="auto",
        help="Chunk size in bars or 'auto' (optimized mode)",
    )
    parser.add_argument("--production-5y", action="store_true", help="Phase 8.8 five-year production collection + validation")
    parser.add_argument(
        "--validate-5y-only",
        action="store_true",
        help="Validate stored 5Y candles only (skip MT5 fetch; use with --production-5y)",
    )
    args = parser.parse_args()

    pipe = MLDataPipeline()
    print("Architecture roles:")
    print(f"  {HIGHER_TIMEFRAME_BIAS} = market bias (kept)")
    print(f"  {CONTEXT_TIMEFRAME} = context validation")
    print(f"  {ENTRY_TIMEFRAME} = entry execution")
    print(f"  {DATA_ONLY_TIMEFRAMES} = data collection only")
    print("Storage: data/ml/raw | processed | datasets | metadata")

    timeframes = _parse_timeframes(args.timeframes) or list(TRADING_TIMEFRAMES)

    if args.production_5y:
        from tradingbot.ml.data.historical_collection_report import run_production_5y
        from tradingbot.ml.data.historical_quality_validator import PRODUCTION_5Y_DAYS, PRODUCTION_TIMEFRAMES

        prod_tfs = _parse_timeframes(args.timeframes) or list(PRODUCTION_TIMEFRAMES)
        result = run_production_5y(
            pipe,
            args.symbol,
            days=PRODUCTION_5Y_DAYS,
            timeframes=prod_tfs,
            workers=args.workers,
            resume=args.resume or True,
            validate_only=args.validate_5y_only,
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.passed else 1

    if args.validate_only:
        report = pipe.validate_historical_storage(args.symbol, timeframes)
        print(json.dumps(report, indent=2))
        return 0 if report.get("overall") == "pass" else 1

    if args.report:
        pipe.print_status_report(args.symbol)
        return 0

    if args.features:
        path = pipe.build_features(args.symbol)
        print(f"  features: {path}")
        return 0 if path else 1

    if args.dataset:
        path = pipe.build_dataset(args.symbol)
        print(f"  dataset: {path}")
        return 0 if path else 1

    if args.events_only:
        for tf in ("H4", "M15", "M5"):
            path = pipe.extract_and_store_events(args.symbol, tf)
            print(f"  events {tf}: {path}")
        news = pipe.export_news()
        print(f"  news calendar: {news}")
        return 0

    if args.historical or args.incremental:
        result = pipe.collect_historical(
            args.symbol,
            timeframes=timeframes,
            days=args.days,
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
            incremental=args.incremental,
        )
        payload = {
            "symbol": result.symbol,
            "timeframes": result.timeframes,
            "stored": {k: str(v) for k, v in result.stored.items()},
            "rejected": result.rejected,
            "bars_fetched": result.bars_fetched,
            "fingerprints": result.fingerprints,
            "manifest": str(result.manifest_path) if result.manifest_path else None,
            "errors": result.errors,
        }
        print(json.dumps(payload, indent=2))
        return 0 if result.stored and not result.errors else (1 if not result.stored else 0)

    if args.optimized:
        chunk_bars: int | str = args.chunk_size
        if chunk_bars != "auto":
            chunk_bars = int(chunk_bars)
        result = pipe.collect_historical_optimized(
            args.symbol,
            timeframes=timeframes,
            days=args.days,
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
            workers=args.workers,
            chunk_bars=chunk_bars,
            resume=args.resume or True,
            parallel_timeframes=args.parallel_timeframes or True,
        )
        payload = {
            "mode": "optimized_8.4",
            "symbol": result.symbol,
            "timeframes": result.timeframes,
            "stored": {k: str(v) for k, v in result.stored.items()},
            "rejected": result.rejected,
            "bars_fetched": result.bars_fetched,
            "fingerprints": result.fingerprints,
            "manifest": str(result.manifest_path) if result.manifest_path else None,
            "errors": result.errors,
        }
        print(json.dumps(payload, indent=2))
        return 0 if result.stored and not result.rejected else (1 if not result.stored else 0)

    result = pipe.run_full(args.symbol, m1_bars=args.m1_bars, tick_hours=args.tick_hours)
    print(
        json.dumps(
            {
                "symbol": result.symbol,
                "candles": {k: str(v) for k, v in result.candles.items()},
                "ticks_days": result.ticks_days,
                "spread_days": result.spread_days,
                "session_days": result.session_days,
                "events": {k: str(v) for k, v in result.events.items()},
                "news_calendar": str(result.news_calendar) if result.news_calendar else None,
                "errors": result.errors,
            },
            indent=2,
        )
    )
    return 1 if result.errors and not result.candles else 0


if __name__ == "__main__":
    raise SystemExit(main())
