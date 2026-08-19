#!/usr/bin/env python3
"""Phase 2 readiness — demo guard, Telegram optional, reporting scripts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def main() -> int:
    import os

    from tradingbot.services.demo_account_guard import verify_demo_account_or_abort

    cfg = load_legacy_config()
    issues: list[str] = []

    print("=== Phase 2 Live Proof Readiness ===")

    demo_ok, demo_msg = verify_demo_account_or_abort(config=cfg)
    print(f"  demo_guard: {'OK' if demo_ok else 'FAIL'} — {demo_msg}")
    if not demo_ok:
        issues.append("demo_guard")

    tg = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    print(f"  telegram: {'configured' if tg else 'optional (not set)'}")
    if not tg:
        print("    -> set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env for alerts")

    for name in ("live_daily_report.py", "live_reconcile.py"):
        path = ROOT / "scripts" / name
        if not path.is_file():
            issues.append(f"missing:{name}")
            print(f"  {name}: MISSING")
        else:
            print(f"  {name}: OK")

    ops = ROOT / "tradingbot" / "services" / "live_ops_service.py"
    print(f"  live_ops_service: {'OK' if ops.is_file() else 'MISSING'}")
    if not ops.is_file():
        issues.append("live_ops_service")

    if issues:
        print("\nPhase 2: NOT READY — fix issues above")
        return 1
    print("\nPhase 2: READY (run LIVE on demo account)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
