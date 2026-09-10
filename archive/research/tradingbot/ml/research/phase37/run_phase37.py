#!/usr/bin/env python3
"""Phase 37 — Filter optimization measurement (read-only, no production changes)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pf(rs: list[float]) -> float:
    w = sum(x for x in rs if x > 0)
    l = abs(sum(x for x in rs if x < 0))
    return round(w / l, 4) if l > 0 else (2.0 if w > 0 else 0.0)


def run_phase37() -> dict:
    replays_path = ROOT / "raw_ml_replay.json"
    exec_path = ROOT / "phase34a_final_report.json"
    marginal_path = ROOT / "filter_marginal_value.json"

    replays: list[dict] = []
    if replays_path.exists():
        replays = json.loads(replays_path.read_text(encoding="utf-8")).get("replays", [])
    if not replays:
        recon = ROOT / "reconstructed_rejections.json"
        if recon.exists():
            replays = json.loads(recon.read_text(encoding="utf-8")).get("events", [])

    exec_pf = 0.31
    if exec_path.exists():
        exec_pf = float(json.loads(exec_path.read_text(encoding="utf-8")).get("executed_statistics", {}).get("profit_factor", 0.31))

    harmful = []
    if marginal_path.exists():
        harmful = [f["filter"] for f in json.loads(marginal_path.read_text(encoding="utf-8")).get("filters", []) if f.get("category") == "HARMFUL"]

    by_filter: dict[str, list] = defaultdict(list)
    for r in replays:
        f = r.get("first_blocking_filter") or r.get("module") or "unknown"
        by_filter[f].append(float(r.get("r_multiple", 0)))

    baseline_r = [float(r.get("r_multiple", 0)) for r in replays if r.get("would_reach_execution")]
    if not baseline_r:
        baseline_r = [float(r.get("r_multiple", 0)) for r in replays]

    simulations: list[dict] = []
    for filt, blocked_rs in sorted(by_filter.items(), key=lambda x: len(x[1]), reverse=True):
        blocked = blocked_rs
        kept = [float(r.get("r_multiple", 0)) for r in replays if (r.get("first_blocking_filter") or r.get("module")) != filt]
        hypo_r = kept + blocked
        simulations.append({
            "filter_removed": filt,
            "blocked_trades": len(blocked),
            "edge_lost_if_removed": round(sum(x for x in blocked if x < 0), 4),
            "edge_gained_if_removed": round(sum(x for x in blocked if x > 0), 4),
            "hypo_pf_if_removed": _pf(hypo_r),
            "pf_delta_vs_baseline": round(_pf(hypo_r) - _pf(baseline_r), 4),
            "category": "HARMFUL" if filt in harmful else "NEUTRAL",
        })

    simulations.sort(key=lambda x: x["pf_delta_vs_baseline"], reverse=True)
    best = simulations[0] if simulations else None

    verdict = "NO_FILTER_REMOVAL_BENEFIT"
    if best and best["pf_delta_vs_baseline"] > 0.2 and best["category"] == "HARMFUL":
        verdict = "FILTER_REMOVAL_MAY_HELP"
    elif best and best["pf_delta_vs_baseline"] > 0.1:
        verdict = "FILTER_REMOVAL_MARGINAL"

    return {
        "now": NOW,
        "verdict": verdict,
        "baseline_replay_pf": _pf(baseline_r),
        "executed_pf": exec_pf,
        "simulations": simulations,
        "recommended_measurement_next": simulations[:3],
        "note": "Simulation only — no production filter changes applied",
    }


def write_all(data: dict) -> None:
    (ROOT / "filter_optimization_matrix.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    (ROOT / "phase37_final_report.json").write_text(json.dumps({
        "phase": "37", "title": "Filter Optimization Measurement", **data,
        "deliverables": ["filter_optimization_matrix.json", "phase37_final_report.json"],
    }, indent=2, default=str), encoding="utf-8")
    print("  wrote filter_optimization_matrix.json", flush=True)
    print("  wrote phase37_final_report.json", flush=True)


def main() -> None:
    data = run_phase37()
    write_all(data)
    print(json.dumps({"verdict": data["verdict"], "top": data["recommended_measurement_next"][:1]}, indent=2))


if __name__ == "__main__":
    main()
