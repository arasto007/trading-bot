#!/usr/bin/env python3
"""Phase 17A — integrated TREND recovery blueprint (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase17a.orchestrator import run_phase17a_blueprint


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 17A TREND recovery blueprint")
    p.add_argument("--base-dir", default=None)
    args = p.parse_args(argv)

    result = run_phase17a_blueprint(base_dir=args.base_dir)
    print(json.dumps({
        "verdict": result["verdict"],
        "reports_dir": result["reports_dir"],
        "answer": result["final_report"].get("answer"),
        "next_phase": result["final_report"].get("next_phase_recommendation"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
