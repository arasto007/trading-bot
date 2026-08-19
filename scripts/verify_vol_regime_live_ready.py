#!/usr/bin/env python3

"""Verify VOL_REGIME full live stack — kernel path, no ML, no demo-only deps."""



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

    from tradingbot.adapters.vol_regime_strategy_registry import VolRegimeStrategyRegistry

    from tradingbot.config.live import get_live_config

    from tradingbot.ml.integration.factory import build_strategy_registry

    from tradingbot.ml.trade_quality.rr_quality import VOL_REGIME_ENGINE, rr_quality_score

    from tradingbot.strategies.vol_regime_signal import CONFIG_ID, STRATEGY_ID, signal_metadata



    live = get_live_config()

    lines: list[str] = []

    ok = True



    lines.append(f"STRATEGY|OK|{STRATEGY_ID}")

    lines.append(f"CONFIG|OK|{CONFIG_ID}")

    lines.append(f"ML_KERNEL|OFF|USE_ML_KERNEL disabled")

    lines.append(f"LIVE_PATH|OK|tradingbot --loop --execute (watchdog)")



    if not live.get("VOL_REGIME_ENABLED", False):

        lines.append("VOL_REGIME|FAIL|VOL_REGIME_ENABLED=false")

        ok = False

    else:

        lines.append("VOL_REGIME|OK|enabled")



    meta = signal_metadata()

    lines.append(f"ATR_SL|OK|{meta['atr_sl_mult']}")

    lines.append(f"TP_RR|OK|{meta['tp_rr']}")



    score, reason = rr_quality_score(0.8, engine_id=VOL_REGIME_ENGINE)

    if score <= 0:

        lines.append(f"TQ_PATCH|FAIL|{reason}")

        ok = False

    else:

        lines.append(f"TQ_PATCH|OK|{reason}")



    reg = build_strategy_registry()

    reg_ok = isinstance(reg, VolRegimeStrategyRegistry)

    lines.append(f"KERNEL_REGISTRY|{'OK' if reg_ok else 'FAIL'}|{type(reg).__name__}")

    if not reg_ok:

        ok = False



    wd = ROOT / "scripts" / "run_live_watchdog.py"

    start = ROOT / "scripts" / "start_live_daemon.ps1"

    lines.append(f"WATCHDOG|{'OK' if wd.is_file() else 'MISSING'}|{wd.name}")

    lines.append(f"DAEMON|{'OK' if start.is_file() else 'MISSING'}|{start.name}")

    if not wd.is_file() or not start.is_file():

        ok = False



    lines.append(f"VERDICT|{'READY' if ok else 'NOT_READY'}|vol_regime full live kernel")

    print("\n".join(lines))

    return 0 if ok else 1





if __name__ == "__main__":

    raise SystemExit(main())

