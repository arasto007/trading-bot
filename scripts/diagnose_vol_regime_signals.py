#!/usr/bin/env python3
"""Deep VOL_REGIME diagnostic — raw signals vs TQ blocks on live M5 data."""

from __future__ import annotations

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
    import MetaTrader5 as mt5
    import pandas as pd

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import attach_mt5_session, safe_release_mt5
    from tradingbot.adapters.symbols import resolve_broker_symbol
    from tradingbot.adapters.vol_regime_strategy_registry import VolRegimeStrategyRegistry
    from tradingbot.domain.models import MarketKey
    from tradingbot.domain.ohlcv import exclude_forming_bar, normalize_ohlcv
    from tradingbot.strategies.vol_regime_signal import evaluate_at_index, prepare_frame

    cfg = load_legacy_config()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== VOL_REGIME diagnostic ({today}) ===")

    from tradingbot.adapters.mt5_utils import is_mt5_lock_held_by_other

    if is_mt5_lock_held_by_other():
        print("SKIP MT5 attach — live bot holds IPC lock (run when bot stopped for full probe)")
        return 0

    if not attach_mt5_session(cfg, strict_account=False, use_lock=False):
        print("MT5 not connected")
        return 1

    try:
        sym = resolve_broker_symbol("XAUUSD", cfg)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 3000)
        if rates is None or len(rates) < 600:
            print(f"Not enough M5 bars: {0 if rates is None else len(rates)}")
            return 1

        df = normalize_ohlcv(pd.DataFrame(rates).assign(time=pd.to_datetime(rates["time"], unit="s", utc=True)).set_index("time"))
        closed = exclude_forming_bar(df, min_rows=80)
        if closed is None:
            print("Closed bars unavailable")
            return 1

        frame = prepare_frame(closed)
        raw_hits = []
        for idx in range(500, len(frame)):
            sig = evaluate_at_index(frame, idx)
            if sig is not None:
                ts = str(frame.index[idx])
                raw_hits.append((ts, sig.direction, sig.atr_pct))

        today_raw = [h for h in raw_hits if h[0].startswith(today)]
        print(f"Bars closed: {len(closed)} | frame: {len(frame)}")
        print(f"Raw VOL_REGIME setups (all window): {len(raw_hits)}")
        print(f"Raw setups TODAY: {len(today_raw)}")
        if today_raw:
            for h in today_raw[-5:]:
                print(f"  {h}")

        reg = VolRegimeStrategyRegistry(cfg)
        mk = MarketKey("XAUUSD", "M5")
        live_sig = reg.generate_signal(mk, closed)
        print(f"\nRegistry (M5 kernel) latest: {live_sig.direction.name if live_sig else 'NONE'}")

        # scan today bar-by-bar through registry
        tq_pass = tq_block = 0
        for idx in range(max(500, len(frame) - 200), len(frame)):
            sub = closed.iloc[: idx + 1]
            if reg.generate_signal(mk, sub) is not None:
                tq_pass += 1
        print(f"Registry signals last ~200 bars: {tq_pass} (includes TQ filter)")

        last = frame.iloc[-1]
        print(
            f"\nLatest bar atr_pct={float(last['atr_pct']):.3f} "
            f"ema20={float(last['ema20']):.2f} ema50={float(last['ema50']):.2f} "
            f"close={float(last['close']):.2f}"
        )
        ap = float(last["atr_pct"])
        in_band = 0.30 <= ap <= 0.70 if ap == ap else False
        print(f"atr_pct in 30-70% band: {in_band}")
    finally:
        safe_release_mt5()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
