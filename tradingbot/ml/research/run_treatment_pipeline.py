#!/usr/bin/env python3
"""Run treatment pipeline phases 52→61 sequentially (research only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

PHASES = {
    "52": "tradingbot.ml.research.phase52.label_audit_v7",
    "53": "tradingbot.ml.research.phase53.execution_funnel_audit",
    "54": "tradingbot.ml.research.phase54.model_sweep",
    "55": "tradingbot.ml.research.phase55.feature_noise_audit",
    "56": "tradingbot.ml.research.phase56.treatment_synthesis",
    "57": "tradingbot.ml.research.phase57.trade_quality_simulation",
    "58": "tradingbot.ml.research.phase58.trend_only_model",
    "59": "tradingbot.ml.research.phase59.horizon_feature_expansion",
    "60": "tradingbot.ml.research.phase60.auc_lift_and_validation",
    "61": "tradingbot.ml.research.phase61.execution_shadow_validation",
}


def run_phase(phase: str, **kwargs) -> dict:
    import importlib

    mod_path = PHASES.get(phase)
    if not mod_path:
        raise ValueError(f"Unknown phase: {phase}")
    mod = importlib.import_module(mod_path)
    if phase == "57":
        mod.main()
        return {"verdict": "PHASE57_COMPLETE"}
    runner = getattr(mod, f"run_phase{phase}")
    if phase == "52" and kwargs.get("sample_size") is not None:
        return runner(sample_size=kwargs["sample_size"])
    return runner()


def main() -> None:
    p = argparse.ArgumentParser(description="Treatment pipeline 52→61")
    p.add_argument("--phase", type=str, default=None, help="Run single phase (52-61)")
    p.add_argument("--from", dest="from_phase", type=str, default="52", help="Start phase for range run")
    p.add_argument("--to", dest="to_phase", type=str, default="61", help="End phase for range run")
    p.add_argument("--sample-size", type=int, default=None, help="Phase 52 sample size override")
    args = p.parse_args()

    order = ["52", "53", "54", "55", "56", "57", "58", "59", "60", "61"]
    if args.phase:
        phases = [args.phase]
    else:
        start = order.index(args.from_phase) if args.from_phase in order else 0
        end = order.index(args.to_phase) if args.to_phase in order else len(order) - 1
        phases = order[start : end + 1]

    results: dict[str, dict] = {}
    for ph in phases:
        print(f"\n=== Phase {ph} ===", flush=True)
        mod_path = PHASES[ph]
        mod = __import__(mod_path, fromlist=["write_all"])
        data = run_phase(ph, sample_size=args.sample_size)
        if ph == "57":
            results[ph] = {"verdict": "PHASE57_COMPLETE"}
        else:
            mod.write_all(data)
            verdict = data.get("verdict")
            if ph in ("58", "59", "60") and (data.get("walk_forward") or data.get("re_gate")):
                verdict = (data.get("walk_forward") or data.get("re_gate") or {}).get("verdict")
            elif ph == "61":
                verdict = data.get("verdict")
            results[ph] = {"verdict": verdict}
        print(f"Phase {ph} done: {results[ph].get('verdict')}", flush=True)

    print(json.dumps({"phases_run": phases, "results": results}, indent=2))


if __name__ == "__main__":
    main()
