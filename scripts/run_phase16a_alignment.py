#!/usr/bin/env python3
"""Phase 16A — trend feature distribution aligner validation CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.feature_alignment.orchestrator import run_phase16a_validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 16A feature alignment validation")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    result = run_phase16a_validation(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        stride=args.stride,
        base_dir=args.base_dir,
    )
    print(result.status)
    print(f"before_max={result.before_max:.6f} after_max={result.after_max:.6f}")
    print(f"actionable_after={result.actionable_after}")
    print(f"checksum_valid={result.bundle_checksum_valid}")
    print(f"reports={result.reports_dir}")
    return 0 if result.status in ("PASS", "READY_FOR_PHASE16B") else 1


if __name__ == "__main__":
    raise SystemExit(main())
