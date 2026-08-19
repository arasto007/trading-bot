"""Entry point: python -m tradingbot [--strategies | --live | --loop | --backtest] [options]"""

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.application.bootstrap import (
    run_demo_cycle,
    run_live_cycle,
    run_strategies_cycle,
)
from tradingbot.application.live_runner import run_live_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="TradingBot (new) kernel")
    parser.add_argument(
        "--strategies",
        action="store_true",
        help="Real strategies (priceaction only) on stub data — no MT5",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="MT5 + real strategies — یک چرخه",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="حلقه دائمی live + سرویس‌های پس‌زمینه (Ctrl+C برای توقف)",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="اجرای بک‌تست روی داده‌ی تاریخی (فاز ۳)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Allow real orders (default: dry-run, no orders sent)",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        help="Paper mode: real ticks + simulated fills + journal (no broker orders)",
    )
    parser.add_argument(
        "--protector",
        action="store_true",
        help="فعال‌سازی PositionProtector قدیم (پیش‌فرض: خاموش — مدیریت توسط هسته)",
    )
    parser.add_argument(
        "--no-recovery",
        action="store_true",
        help="غیرفعال کردن PositionRecoveryService",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Write live heartbeat without MT5 or starting the loop (Phase 20Y-1)",
    )
    # گزینه‌های بک‌تست
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--tf", default="M15")
    parser.add_argument("--bars", type=int, default=1500)
    parser.add_argument("--min-confidence", type=float, default=None)
    args = parser.parse_args()

    if args.healthcheck:
        from tradingbot.services.live_loop_health import (
            print_healthcheck_report,
            write_healthcheck_heartbeat,
        )

        path = write_healthcheck_heartbeat()
        print(print_healthcheck_report())
        print(f"TradingBot (new) — HEALTHCHECK heartbeat={path}")
        return
    if args.backtest:
        _run_backtest(args)
    elif args.loop:
        mode = "PAPER" if args.paper else ("LIVE" if args.execute else "DRY-RUN")
        print(f"TradingBot (new) — LIVE LOOP [{mode}] (Ctrl+C to stop)")
        run_live_loop(
            dry_run=not args.execute and not args.paper,
            paper=args.paper,
            enable_protector=args.protector,
            enable_recovery=not args.no_recovery,
        )
    elif args.strategies:
        print("TradingBot (new) — strategies test")
        run_strategies_cycle()
    elif args.live:
        if args.paper:
            os.environ["TRADINGBOT_PAPER"] = "1"
            os.environ.pop("TRADINGBOT_DRY_RUN", None)
            print("TradingBot (new) — LIVE MT5 cycle [PAPER]")
        else:
            print("TradingBot (new) — LIVE MT5 cycle")
        run_live_cycle(dry_run=not args.execute and not args.paper, paper=args.paper)
    else:
        print("TradingBot (new) — demo (stub)")
        run_demo_cycle()


def _run_backtest(args) -> None:
    import asyncio

    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine, report

    cfg = BacktestConfig(
        symbols=[args.symbol],
        timeframe=args.tf,
        bars=args.bars,
        min_confidence=args.min_confidence,
    )
    print(f"TradingBot (new) — BACKTEST {args.symbol} {args.tf} bars={args.bars}")
    engine = BacktestEngine(cfg)
    result = asyncio.run(engine.run())
    print(report(result))


if __name__ == "__main__":
    main()
