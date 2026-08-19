#!/usr/bin/env python3
"""Run LIVE profitable robot roadmap phases L0-L6 (research orchestrator)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

PHASES = {
    "L1": "tradingbot.ml.research.live_l1.build_v8_dataset",
    "L1b": "tradingbot.ml.research.live_l1.expand_v8_labels",
    "L2": "tradingbot.ml.research.live_l2.edge_discovery",
    "L2r2": "tradingbot.ml.research.live_l2.edge_discovery_round2",
    "L2.5": "tradingbot.ml.research.live_l2.sl_tp_sweep",
    "L2.6": "tradingbot.ml.research.live_l2.edge_discovery_l26",
    "L2.7": "tradingbot.ml.research.live_l2.edge_discovery_l27",
    "L3": "tradingbot.ml.research.live_l3.execution_validation",
    "L4": "tradingbot.ml.research.live_l4.signal_ml_refinement",
    "L4prep": "tradingbot.ml.research.live_l4.v8_regime_ml_test",
    "BT-gate": "tradingbot.ml.research.live_bt.backtest_gate",
    "RR-research": "tradingbot.ml.research.live_bt.rr_production_research",
    "L5": "tradingbot.ml.research.live_l5.paper_trading_setup",
    "L6": "tradingbot.ml.research.live_l6.deploy_gate_review",
    "L6-auto": "tradingbot.ml.research.live_l6.l6_auto_review",
    "integration-readiness": "tradingbot.ml.research.live_l6.integration_readiness",
    "L6-plan": "tradingbot.ml.research.live_l6.l6_integration_plan",
}


def run_phase(phase: str, **kwargs) -> dict:
    if phase == "L0":
        roadmap = ROOT / "LIVE_PROFIT_ROADMAP.json"
        if not roadmap.is_file():
            return {"verdict": "ROADMAP_MISSING", "path": str(roadmap)}
        data = json.loads(roadmap.read_text(encoding="utf-8"))
        l0 = next((p for p in data.get("phases", []) if p.get("id") == "L0"), None)
        return {"verdict": "L0_INFO", "phase": l0, "roadmap": str(roadmap)}

    mod_path = PHASES.get(phase)
    if not mod_path:
        raise ValueError(f"Unknown phase: {phase}. Available: L0, {', '.join(PHASES)}")

    import importlib

    mod = importlib.import_module(mod_path)
    if phase in ("L2", "L2r2"):
        stride = kwargs.get("stride")
        runner = mod.run_edge_discovery if phase == "L2" else mod.run_edge_discovery_round2
        data = runner(stride_override=stride)
        mod.write_report(data)
        return data
    runner = getattr(mod, "main", None)
    if runner is None:
        return {"verdict": "NOT_IMPLEMENTED", "phase": phase, "module": mod_path}
    return runner()


def main() -> None:
    p = argparse.ArgumentParser(description="LIVE profit roadmap pipeline L0-L6")
    p.add_argument(
        "--phase",
        type=str,
        required=True,
        help="Phase: L0, L1, L1b, L2, L2r2, L2.5, L2.6, L2.7, L3, L4, L4prep, BT-gate, RR-research, L5, L6, L6-auto, L6-plan, integration-readiness",
    )
    p.add_argument("--stride", type=int, default=None, help="L2/L2r2 bar stride override")
    args = p.parse_args()

    print(f"\n=== LIVE Phase {args.phase} ===", flush=True)
    data = run_phase(args.phase, stride=args.stride)
    verdict = data.get("verdict", "DONE")
    print(f"Phase {args.phase} done: {verdict}", flush=True)
    print(json.dumps({"phase": args.phase, "verdict": verdict}, indent=2))


if __name__ == "__main__":
    main()
