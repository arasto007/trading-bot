#!/usr/bin/env python3
"""بررسی کامل تنظیمات live — نماد MT5، پریست‌ها، اتصال."""

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

# Presets remain available for research; only ACTIVE_LIVE_TIMEFRAMES are required live.
EXPECTED_PRESETS = {
    "M5": "gold_ny_sweep",
    "M15": "atr_tight_gold",
    "H4": "gold_h4_swing",
}


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.symbols import resolve_broker_symbol
    from tradingbot.config.live import PRIMARY_SYMBOL, get_live_config
    from tradingbot.config.engine_settings import config as engine_config
    from tradingbot.config.legacy_settings import kernel_settings_from_legacy
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.config.pa_symbol_tf_presets import is_pa_cell_enabled
    from tradingbot.config.strategies import ACTIVE_STRATEGIES
    import MetaTrader5 as mt5

    cfg = load_legacy_config()
    live = get_live_config()
    if live.get("VOL_REGIME_ENABLED"):
        from tradingbot.adapters.mt5_utils import safe_release_mt5

        print("=== VOL_REGIME mode — delegating to vol_regime preflight ===")
        from scripts.check_vol_regime_live_setup import main as vol_main

        rc = vol_main()
        if rc == 0:
            ks = kernel_settings_from_legacy()
            print(f"\n=== Kernel (VOL_REGIME) ===")
            print(f"  timeframes={ks.timeframes} (M5-only expected)")
            if set(ks.timeframes) != {"5m"}:
                print("  WARN: expected timeframes=['5m'] only")
        safe_release_mt5()
        return rc

    ks = kernel_settings_from_legacy()
    issues: list[str] = []
    sym = cfg.get("SYMBOLS", [PRIMARY_SYMBOL])[0]

    print("=== MT5 Connection ===")
    from tradingbot.adapters.mt5_utils import attach_mt5_session, safe_release_mt5

    ok = attach_mt5_session(cfg, symbols=[sym], strict_account=True, use_lock=False)
    if not ok:
        print("  FAIL — MT5 not attached (open terminal manually + login, then Ctrl+E)")
        return 1
    acc = mt5.account_info()
    term = mt5.terminal_info()
    print(f"  OK login={acc.login} server={acc.server}")
    print(f"  balance={acc.balance:.2f} equity={acc.equity:.2f}")

    sym = cfg.get("SYMBOLS", [PRIMARY_SYMBOL])[0]
    broker = resolve_broker_symbol(sym, cfg)
    from tradingbot.adapters.mt5_health import check_autotrading_ready

    auto_ok, auto_msg = check_autotrading_ready(sym, config=cfg)
    print(f"  AutoTrading probe: {auto_msg}")
    if not auto_ok:
        issues.append(f"MT5: {auto_msg}")
    elif term is not None and (
        not getattr(term, "trade_allowed", True) or getattr(term, "tradeapi_disabled", False)
    ):
        print(
            "  note: terminal flag says AutoTrading OFF but order_check passed — OK for live"
        )

    print("\n=== Symbol ===")
    info = mt5.symbol_info(broker)
    tick = mt5.symbol_info_tick(broker)
    if info is None:
        issues.append(f"نماد {broker} در MT5 پیدا نشد")
    else:
        spread = (tick.ask - tick.bid) if tick else 0
        print(f"  config={sym} -> broker={broker}")
        print(f"  visible={info.visible} spread={spread:.3f} digits={info.digits}")
        if not info.visible:
            issues.append(f"نماد {broker} در Market Watch نیست")

    print("\n=== Live Config ===")
    print(f"  symbols={ks.symbols}")
    print(f"  timeframes={ks.timeframes}")
    print(f"  loop={ks.cycle_interval_seconds}s risk={cfg.get('RISK_PER_TRADE')}")
    print(f"  strategies={[k for k, v in ACTIVE_STRATEGIES.items() if v]}")

    from tradingbot.adapters.timeframes import to_legacy
    from tradingbot.services.live_loop_health import live_timeframe_health

    tfh = live_timeframe_health(kernel_timeframes=list(ks.timeframes))
    print("\n=== Timeframes ===")
    print(f"  SUPPORTED_TIMEFRAMES = {','.join(tfh['supported'])}")
    print(f"  ACTIVE_LIVE_TIMEFRAMES = {','.join(tfh['active'])}")
    print(f"  TIMEFRAME_CONFIGURATION_OK = {'YES' if tfh['ok'] else 'NO'}")
    issues.extend(tfh["issues"])

    stf = engine_config._get_strategy_timeframes()
    pa_tfs = stf.get("priceaction", [])
    active_set = set(tfh["active"])
    for k_tf in active_set:
        legacy_tf = to_legacy(k_tf)
        if legacy_tf not in pa_tfs:
            issues.append(
                f"priceaction strategy_timeframes missing active live TF {legacy_tf}: {pa_tfs}"
            )

    print("\n=== Per-TF Presets (supported; only ACTIVE_LIVE_TIMEFRAMES must be live) ===")
    tf_map = {"M5": "5m", "M15": "15m", "H4": "4h"}
    for k_tf, legacy_tf in tf_map.items():
        pa = get_price_action_config(sym, legacy_tf)
        en = is_pa_cell_enabled(sym, legacy_tf)
        exp = EXPECTED_PRESETS[k_tf]
        role = "ACTIVE_LIVE" if k_tf in active_set else "supported_only"
        print(
            f"  {k_tf}: preset={pa.get('PRESET')} enabled={en} mode={pa.get('GOLD_STRATEGY_MODE')} "
            f"conf={pa.get('MIN_CONFIDENCE')} sl_atr={pa.get('SL_ATR_MULT')} "
            f"session={pa.get('SESSION_START_HOUR')}-{pa.get('SESSION_END_HOUR')} "
            f"max_day={pa.get('MAX_TRADES_PER_DAY')} [{role}]"
        )
        if k_tf not in active_set:
            continue
        if not en:
            issues.append(f"{k_tf} PA preset must be enabled for active live TF")
        if pa.get("PRESET") != exp:
            issues.append(f"{k_tf}: expected preset {exp}, got {pa.get('PRESET')}")

    if is_pa_cell_enabled(sym, "1h"):
        issues.append("H1 must stay disabled")

    print("\n=== Issues ===")
    if issues:
        for i in issues:
            print(f"  ! {i}")
        safe_release_mt5()
        return 2
    print("  OK — live config consistent (ACTIVE_LIVE_TIMEFRAMES = M5)")
    safe_release_mt5()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
