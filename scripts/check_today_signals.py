#!/usr/bin/env python3
"""Summarize today's kernel cycles and scan VOL_REGIME on live M5 bars."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import attach_mt5_session, safe_release_mt5
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.integration.factory import build_strategy_registry
    from tradingbot.strategies.vol_regime_signal import prepare_frame, scan_signals

    cfg = load_legacy_config()
    db = ROOT / "data" / "trade_journal.db"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"=== Today signal summary ({today}) ===")

    if db.is_file():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT state, detail, COUNT(*) AS n FROM cycle_events WHERE ts LIKE ? GROUP BY state, detail ORDER BY n DESC LIMIT 20",
            (f"{today}%",),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM cycle_events WHERE ts LIKE ?", (f"{today}%",)).fetchone()[0]
        print(f"Journal cycles today: {total}")
        for r in rows:
            print(f"  {r['n']:4d}x  {r['state']} — {r['detail'][:80]}")
        conn.close()
    else:
        print("No trade_journal.db yet")

    if not attach_mt5_session(cfg, strict_account=False, use_lock=False):
        print("MT5 offline — skip live bar scan")
        return 0

    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.symbols import resolve_broker_symbol

        sym = resolve_broker_symbol("XAUUSD", cfg)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 500)
        if rates is None or len(rates) == 0:
            print("No M5 rates from MT5")
            return 0

        import pandas as pd

        from tradingbot.domain.ohlcv import normalize_ohlcv

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        df = normalize_ohlcv(df)
        frame = prepare_frame(df)
        hits = scan_signals(frame)
        today_hits = [h for h in hits if str(h.get("time", "")).startswith(today)]
        print(f"\nVOL_REGIME scan on last 500 M5 bars:")
        print(f"  Total setups in window: {len(hits)}")
        print(f"  Setups today (UTC date): {len(today_hits)}")
        if today_hits:
            for h in today_hits[-5:]:
                print(f"    {h}")

        reg = build_strategy_registry(cfg)
        mk = MarketKey("XAUUSD", "5m")
        sig = reg.generate_signal(mk, df)
        print(f"\nLatest bar signal: {sig.direction.name if sig else 'NONE'}")
        if sig:
            print(f"  conf={sig.confidence:.2f} sl={sig.stop_loss} tp={sig.take_profit}")
    finally:
        safe_release_mt5()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
