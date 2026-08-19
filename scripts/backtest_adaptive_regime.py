#!/usr/bin/env python3
"""Compare adaptive multi-regime vs VOL_REGIME-only on recent M5 XAUUSD data."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def _scan_registry(name: str, registry, closed, mk) -> list[tuple[str, str, str]]:
    from tradingbot.strategies.vol_regime_signal import prepare_frame

    frame = prepare_frame(closed)
    hits: list[tuple[str, str, str]] = []
    for idx in range(500, len(frame)):
        sub = closed.iloc[: idx + 1]
        sig = registry.generate_signal(mk, sub)
        if sig is not None:
            meta = sig.metadata or {}
            hits.append(
                (
                    str(frame.index[idx]),
                    sig.direction.name,
                    str(meta.get("sub_strategy") or meta.get("config_id") or name),
                )
            )
    return hits


def main() -> int:
    import MetaTrader5 as mt5
    import pandas as pd

    from tradingbot.adapters.adaptive_regime_strategy_registry import (
        AdaptiveRegimeStrategyRegistry,
    )
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import attach_mt5_session, safe_release_mt5
    from tradingbot.adapters.symbols import resolve_broker_symbol
    from tradingbot.adapters.vol_regime_strategy_registry import VolRegimeStrategyRegistry
    from tradingbot.domain.models import MarketKey
    from tradingbot.domain.ohlcv import exclude_forming_bar, normalize_ohlcv

    cfg = load_legacy_config()
    print("=== Adaptive vs VOL_REGIME backtest scan (last 3000 M5 bars) ===")
    if not attach_mt5_session(cfg, strict_account=False, use_lock=False):
        print("MT5 not connected")
        return 1
    try:
        sym = resolve_broker_symbol("XAUUSD", cfg)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 3000)
        df = normalize_ohlcv(
            pd.DataFrame(rates).assign(
                time=pd.to_datetime(rates["time"], unit="s", utc=True)
            ).set_index("time")
        )
        closed = exclude_forming_bar(df, min_rows=80)
        if closed is None:
            print("Not enough bars")
            return 1
        mk = MarketKey("XAUUSD", "M5")

        vol_hits = _scan_registry("VOL_REGIME", VolRegimeStrategyRegistry(cfg), closed, mk)
        adp_hits = _scan_registry("ADAPTIVE", AdaptiveRegimeStrategyRegistry(cfg), closed, mk)

        print(f"VOL_REGIME-only signals: {len(vol_hits)}")
        print(f"Adaptive regime signals:  {len(adp_hits)}")
        uplift = len(adp_hits) - len(vol_hits)
        print(f"Uplift: {uplift:+d} ({100 * uplift / max(len(vol_hits), 1):+.0f}%)")

        if adp_hits:
            from collections import Counter

            subs = Counter(h[2] for h in adp_hits)
            print("\nAdaptive sub-strategies:")
            for k, v in subs.most_common():
                print(f"  {k}: {v}")
            print("\nLast 5 adaptive signals:")
            for h in adp_hits[-5:]:
                print(f"  {h}")
    finally:
        safe_release_mt5()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
