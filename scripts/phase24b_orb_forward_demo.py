#!/usr/bin/env python3
"""Phase 24B ORB forward demo CLI (research-only)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.research import orb_forward_demo as demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 24B ORB forward demo")
    parser.add_argument("--preflight", action="store_true", help="Run daily preflight checks")
    parser.add_argument("--init", action="store_true", help="Record forward window start")
    parser.add_argument("--cycle", action="store_true", help="Run one forward observation/execution cycle")
    parser.add_argument("--execute", action="store_true", help="Allow demo order_send (requires --cycle)")
    parser.add_argument("--rollup", action="store_true", help="Roll up metrics and write phase24b_result.txt")
    parser.add_argument("--today", action="store_true", help="Alias: rollup for current day")
    args = parser.parse_args(argv)

    if not any((args.preflight, args.init, args.cycle, args.rollup, args.today)):
        args.rollup = True

    cfg = load_legacy_config()
    frozen = demo.load_frozen_orb_config()

    if args.init:
        payload = demo.init_forward_start()
        print(json.dumps(payload, indent=2))
    if args.preflight:
        record = demo.preflight_daily(cfg, frozen)
        print(json.dumps(record, indent=2, default=str))
    if args.cycle:
        if args.execute and os.getenv("PHASE24B_ORB_DEMO", "").strip() != "1":
            print("PHASE24B_ORB_DEMO=1 required for --cycle --execute", file=sys.stderr)
            return 2
        result = demo.run_cycle(cfg, execute=args.execute)
        print(json.dumps(result, indent=2, default=str))
    if args.rollup or args.today:
        summary = demo.rollup_metrics()
        print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
