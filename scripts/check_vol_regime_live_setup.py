#!/usr/bin/env python3

"""Pre-flight for VOL_REGIME live — MT5 attach, any account, candles."""



from __future__ import annotations



import sys

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

    from tradingbot.adapters.mt5_health import check_autotrading_ready

    from tradingbot.adapters.mt5_utils import attach_mt5_session, safe_release_mt5

    from tradingbot.adapters.symbols import resolve_broker_symbol

    from tradingbot.config.live import get_live_config

    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles

    from tradingbot.strategies.vol_regime_signal import CONFIG_ID, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME



    cfg = load_legacy_config()

    live = get_live_config()

    issues: list[str] = []



    print("=== VOL_REGIME Live Pre-flight (full power) ===")

    print(f"  strategy=VOL_REGIME config={CONFIG_ID}")

    print(f"  symbol={DEFAULT_SYMBOL} tf={DEFAULT_TIMEFRAME}")

    print(f"  VOL_REGIME_ENABLED={live.get('VOL_REGIME_ENABLED', False)}")



    if not live.get("VOL_REGIME_ENABLED", False):

        issues.append("VOL_REGIME_ENABLED is false in live config")



    print("\n=== MT5 (attach-only) ===")

    connected = attach_mt5_session(cfg, symbols=[DEFAULT_SYMBOL], strict_account=False)

    if not connected:

        print("  FAIL — MT5 not attached (open terminal + login)")

        return 1



    import MetaTrader5 as mt5



    acc = mt5.account_info()

    if acc is None:

        issues.append("MT5 account_info unavailable")

    else:

        print(f"  login={acc.login} server={acc.server}")

        print(f"  balance={acc.balance} equity={acc.equity} trade_mode={acc.trade_mode}")



    sym = DEFAULT_SYMBOL

    broker = resolve_broker_symbol(sym, cfg)

    auto_ok, auto_msg = check_autotrading_ready(sym, config=cfg)

    print(f"  AutoTrading: {auto_msg}")

    if not auto_ok:

        issues.append(f"AutoTrading: {auto_msg}")



    info = mt5.symbol_info(broker)

    if info is None:

        issues.append(f"Symbol {broker} not found in MT5")

    else:

        print(f"  symbol={broker} visible={info.visible}")



    safe_release_mt5()



    print("\n=== Candle data ===")

    candles = resolve_fullest_candles(DEFAULT_SYMBOL, DEFAULT_TIMEFRAME)

    if candles is None or candles.empty:

        issues.append("No M5 candle parquet — run refresh or collect data")

    else:

        print(f"  rows={len(candles)} end={candles.index.max()}")



    print("\n=== Issues ===")

    if issues:

        for item in issues:

            print(f"  ! {item}")

        return 2

    print("  OK — ready for VOL_REGIME live kernel (--loop --execute)")

    return 0





if __name__ == "__main__":

    raise SystemExit(main())

