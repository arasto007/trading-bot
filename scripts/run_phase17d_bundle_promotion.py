#!/usr/bin/env python3

"""Phase 17D — production bundle promotion (safe deployment)."""



from __future__ import annotations



import argparse

import json

import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:

    sys.path.insert(0, str(ROOT))



from tradingbot.ml.phase17d.config import DEFAULT_SYMBOL, DEFAULT_TIMEFRAME

from tradingbot.ml.phase17d.orchestrator import run_phase17d_promotion





def main(argv: list[str] | None = None) -> int:

    p = argparse.ArgumentParser(description="Phase 17D production bundle promotion")

    p.add_argument("--symbol", default=DEFAULT_SYMBOL)

    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)

    p.add_argument("--base-dir", default=None)

    p.add_argument("--skip-regression", action="store_true")

    args = p.parse_args(argv)



    result = run_phase17d_promotion(

        symbol=args.symbol,

        timeframe=args.timeframe,

        base_dir=args.base_dir,

        skip_regression=args.skip_regression,

        project_root=ROOT,

    )

    print(json.dumps({

        "verdict": result["verdict"],

        "reports_dir": result["reports_dir"],

        "checks": result["checks"],

        "summary": result["final_report"].get("summary"),

    }, indent=2))

    return 0 if result["verdict"] == "READY_FOR_LIVE_SHADOW" else 1





if __name__ == "__main__":

    sys.exit(main())

