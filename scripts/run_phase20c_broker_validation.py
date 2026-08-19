#!/usr/bin/env python3
"""Phase 20C — real broker execution validation (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase20c.orchestrator import run_phase20c_validation


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 20C real broker execution validation")
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase20c_validation(base_dir=args.base_dir)
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "real_fill_count": result["real_fill_count"],
        "pending_analyses": result["final_report"].get("pending_analyses"),
        "overall_score": (result.get("score") or {}).get("overall_score"),
    }, indent=2))
    # WAITING is success (not a failure); LIVE_VALIDATED is success
    return 0


if __name__ == "__main__":
    sys.exit(main())
