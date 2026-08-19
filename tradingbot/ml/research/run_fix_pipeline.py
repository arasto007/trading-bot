#!/usr/bin/env python3
"""Run fix pipeline phases 62→70 sequentially (research only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

PHASES = {
    "62": "tradingbot.ml.research.phase62.trade_quality_shadow_analysis",
    "63": "tradingbot.ml.research.phase63.trade_quality_shadow_calibration",
    "64": "tradingbot.ml.research.phase64.adaptive_risk_shadow_review",
    "65": "tradingbot.ml.research.phase65.auc_feature_lift",
    "66": "tradingbot.ml.research.phase66.label_horizon_experiments",
    "67": "tradingbot.ml.research.phase67.trend_ensemble_specialization",
    "68": "tradingbot.ml.research.phase68.combined_shadow_revalidation",
    "70": "tradingbot.ml.research.phase70.fix_roadmap_final_review",
}


def run_phase(phase: str, **kwargs) -> dict:
    import importlib

    mod_path = PHASES.get(phase)
    if not mod_path:
        raise ValueError(f"Phase {phase} not yet implemented — see FIX_ROADMAP.json")
    mod = importlib.import_module(mod_path)
    runner = getattr(mod, f"run_phase{phase}")
    return runner()


def main() -> None:
    p = argparse.ArgumentParser(description="Fix pipeline 62→70 (research only)")
    p.add_argument("--phase", type=str, default=None, help="Run single phase (62-70)")
    p.add_argument("--from", dest="from_phase", type=str, default="62", help="Start phase for range run")
    p.add_argument("--to", dest="to_phase", type=str, default="62", help="End phase for range run")
    args = p.parse_args()

    order = ["62", "63", "64", "65", "66", "67", "68", "69", "70"]
    if args.phase:
        phases = [args.phase]
    else:
        start = order.index(args.from_phase) if args.from_phase in order else 0
        end = order.index(args.to_phase) if args.to_phase in order else 0
        phases = order[start : end + 1]

    results: dict[str, dict] = {}
    for ph in phases:
        print(f"\n=== Fix Phase {ph} ===", flush=True)
        mod_path = PHASES[ph]
        mod = __import__(mod_path, fromlist=["write_all"])
        data = run_phase(ph)
        mod.write_all(data)
        results[ph] = {"verdict": data.get("verdict")}
        print(f"Phase {ph} done: {results[ph].get('verdict')}", flush=True)

    print(json.dumps({"phases_run": phases, "results": results}, indent=2))


if __name__ == "__main__":
    main()
