#!/usr/bin/env python3
"""Phase 18B — controlled live gate (final GO/NO-GO)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase18b.config import DEFAULT_DAYS, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME
from tradingbot.ml.phase18b.orchestrator import run_phase18b_go_live


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 18B controlled live gate")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase18b_go_live(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        base_dir=args.base_dir,
        project_root=ROOT,
    )
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "checks": result["checks"],
        "checklist_summary": result["checklist"].get("summary"),
    }, indent=2))
    return 0 if result["verdict"] in ("READY_FOR_FULL_LIVE", "READY_FOR_LIMITED_LIVE") else 1


if __name__ == "__main__":
    sys.exit(main())
