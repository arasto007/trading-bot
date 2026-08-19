#!/usr/bin/env python3
"""
Read-only live candle refresh — attach-only, respects MT5 IPC lock.

Safe to run while MT5 GUI is open. Skips when another process recently refreshed
or holds the IPC lock (e.g. live trading loop).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.market_cache import ParquetCache
from tradingbot.adapters.mt5_utils import (
    attach_mt5_session,
    is_mt5_lock_held_by_other,
    is_refresh_recent,
    mark_refresh_done,
    mt5_ipc_lock,
)
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.config.dotenv_loader import load_dotenv
from tradingbot.domain.ohlcv import normalize_ohlcv
from tradingbot.ml.data.mt5_fetch import fetch_candles

load_dotenv()

LOG_DIR = ROOT / "logs"


def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("refresh_live_candles")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "refresh_live_candles.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def refresh_symbol_candles(
    config: dict,
    symbol: str,
    timeframe: str,
    *,
    bars: int = 3000,
    logger: logging.Logger | None = None,
) -> dict:
    log = logger or _setup_logging()

    if is_refresh_recent(config):
        log.info("Skip — recent refresh within cooldown")
        return {"skipped": True, "reason": "recent_refresh"}

    if is_mt5_lock_held_by_other(config):
        log.info("Skip — live process holds MT5 IPC lock")
        return {"skipped": True, "reason": "mt5_lock_held"}

    with mt5_ipc_lock(config, purpose="refresh_candles"):
        if not attach_mt5_session(config, symbols=[symbol], use_lock=False):
            log.error("attach_mt5_session failed")
            return {"success": False, "reason": "attach_failed"}

        df = fetch_candles(config, symbol, timeframe, bars=bars)
        if df is None or df.empty:
            log.error("No candles fetched for %s %s", symbol, timeframe)
            return {"success": False, "reason": "no_data"}

        df = normalize_ohlcv(df)
        data_dir = config.get("data_dir") or config.get("DATA_DIR") or "data"
        cache = ParquetCache(data_dir)
        legacy_tf = to_legacy(timeframe)
        cache.store(symbol, legacy_tf, df)

        broker = resolve_broker_symbol(symbol, config)
        max_ts = df.index.max().isoformat() if len(df) else None
        log.info("Stored %d bars for %s (%s) max=%s", len(df), symbol, broker, max_ts)

        mark_refresh_done(
            config,
            purpose="refresh_live_candles",
            extra={"symbol": symbol, "timeframe": timeframe, "bars": len(df), "max_ts": max_ts},
        )
        return {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": len(df),
            "max_timestamp": max_ts,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live candle refresh (attach-only)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--force", action="store_true", help="Ignore refresh cooldown")
    args = parser.parse_args()

    logger = _setup_logging()
    config = load_legacy_config()

    if args.force:
        marker = config.get("BASE_DIR", ".")
        from tradingbot.adapters.mt5_utils import mt5_refresh_marker_path

        try:
            mt5_refresh_marker_path(config).unlink(missing_ok=True)
        except Exception:
            pass

    result = refresh_symbol_candles(
        config,
        args.symbol.upper(),
        args.timeframe.upper(),
        bars=args.bars,
        logger=logger,
    )
    print(json.dumps(result, indent=2))
    if result.get("skipped"):
        return 0
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
