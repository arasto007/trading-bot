#!/usr/bin/env python3
"""Phase 10A — generate engine health dashboard artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.services.engine_health_dashboard import (
    build_engine_health_dashboard,
    format_phase10a_result,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Engine health dashboard (Phase 10A)")
    parser.add_argument("--base-dir", default=None, help="Project root override")
    parser.add_argument("--lookback-days", type=int, default=30)
    args = parser.parse_args(argv)

    payload = build_engine_health_dashboard(args.base_dir, lookback_days=args.lookback_days)
    print(format_phase10a_result(payload))
    from tradingbot.services.live_loop_health import print_healthcheck_report

    print(print_healthcheck_report(include_mt5_probe=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
