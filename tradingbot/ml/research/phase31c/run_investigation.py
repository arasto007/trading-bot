"""Phase 31C — realistic exit edge recovery (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase31a.data_loader import build_master_frame
from tradingbot.ml.research.phase31b.metrics import compute_metrics
from tradingbot.ml.research.phase31c.exit_simulators import EXIT_CANDIDATES, load_candles
from tradingbot.ml.research.phase31c.ranking import rank_candidates
from tradingbot.ml.research.phase31c.validation import (
    bootstrap_validation,
    montecarlo_validation,
    rejection_check,
    walkforward_validation,
)

PHASE_DIR = Path(__file__).resolve().parent
CACHE_CANDLES = PHASE_DIR / "_cache" / "candles_m5.parquet"
VERDICTS = {"REALISTIC_EXIT_FOUND", "NO_REALISTIC_IMPROVEMENT"}


def _write(name: str, payload: dict | list) -> None:
    def _safe(obj):
        if isinstance(obj, dict):
            return {k: _safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_safe(x) for x in obj]
        if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
            return None
        return obj

    (PHASE_DIR / name).write_text(json.dumps(_safe(payload), indent=2, default=str), encoding="utf-8")


def determine_verdict(ranked: list[dict], baseline: dict, *, sim_baseline: dict | None = None) -> str:
    compare_pf = (sim_baseline or baseline).get("profit_factor", baseline["profit_factor"])
    if not ranked:
        return "NO_REALISTIC_IMPROVEMENT"
    best = ranked[0]
    if best["pf_gain"] < 0.03:
        return "NO_REALISTIC_IMPROVEMENT"
    if best.get("walkforward", {}).get("walkforward_pass") and best["pf_gain"] >= 0.05:
        return "REALISTIC_EXIT_FOUND"
    if best["ranking_score"] >= 0.65 and best["pf_gain"] > 0 and best.get("walkforward", {}).get("stable"):
        return "REALISTIC_EXIT_FOUND"
    return "NO_REALISTIC_IMPROVEMENT"


def run_phase31c() -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    df, meta = build_master_frame()
    trades = df.to_dict("records")
    frame = load_candles(CACHE_CANDLES, trades=trades)

    # Set rejection baseline after first candidate
    candidates = []
    for tid, name, fn, mmeta in EXIT_CANDIDATES:
        trade_rows = []
        for trade in trades:
            sim = fn(trade, frame)
            trade_rows.append({
                "trade_id": trade.get("trade_id"),
                "timestamp": trade.get("timestamp"),
                "direction": trade.get("direction"),
                "baseline_pnl": float(trade["pnl"]),
                "pnl": float(sim["pnl"]),
                "pnl_r": float(sim.get("pnl_r") or 0),
                "exit_reason": sim.get("exit_reason"),
                "duration_bars": int(sim.get("duration_bars") or 0),
                "capture_efficiency": sim.get("capture_efficiency"),
            })
        metrics = compute_metrics(
            [{"pnl": r["pnl"], "pnl_r": r["pnl_r"], "timestamp": r["timestamp"],
              "exit_timestamp": r["timestamp"], "duration_bars": r["duration_bars"],
              "direction": r["direction"]} for r in trade_rows],
            label=name,
        )
        exit_dist: dict[str, int] = {}
        for r in trade_rows:
            er = str(r.get("exit_reason") or "unknown")
            exit_dist[er] = exit_dist.get(er, 0) + 1
        caps = [r["capture_efficiency"] for r in trade_rows if r.get("capture_efficiency") is not None]
        boot = bootstrap_validation(trade_rows)
        mc = montecarlo_validation(trade_rows)
        wf = walkforward_validation(trade_rows)
        candidates.append({
            "candidate_id": tid,
            "name": name,
            "meta": mmeta,
            "metrics": metrics,
            "exit_distribution": exit_dist,
            "avg_capture_efficiency": round(sum(caps) / len(caps), 4) if caps else None,
            "avg_holding_bars": round(sum(r["duration_bars"] for r in trade_rows) / max(len(trade_rows), 1), 2),
            "bootstrap": boot,
            "montecarlo": mc,
            "walkforward": wf,
            "uses_future_info": False,
            "live_implementable": True,
            "implementation_complexity": "LOW" if mmeta.get("simplicity", 5) >= 8 else "MEDIUM" if mmeta.get("simplicity", 5) >= 6 else "HIGH",
        })
        _write(f"exit_candidate_{tid}.json", {
            "phase": "31C", **candidates[-1],
            "generated_utc": ts,
        })

    baseline_c = next(c for c in candidates if c["name"] == "baseline_current")
    baseline = baseline_c["metrics"]
    sim_baseline_c = next(c for c in candidates if c["name"] == "hybrid_b_proxy")
    sim_baseline = sim_baseline_c["metrics"]

    for c in candidates:
        c["rejection"] = rejection_check(c, baseline["profit_factor"])

    ranked = rank_candidates(candidates, baseline, sim_baseline=sim_baseline)
    verdict = determine_verdict(ranked, baseline, sim_baseline=sim_baseline)
    best_realworld = ranked[0] if ranked else None

    _write("counterfactual_results.json", {
        "phase": "31C",
        "production_baseline": baseline,
        "simulation_baseline": {
            "name": "hybrid_b_proxy",
            "metrics": sim_baseline,
        },
        "candidates": [{k: c[k] for k in ("candidate_id", "name", "metrics", "rejection", "walkforward")} for c in candidates],
        "generated_utc": ts,
    })
    _write("walkforward_validation.json", {
        "phase": "31C",
        "results": {c["name"]: c["walkforward"] for c in candidates},
        "generated_utc": ts,
    })
    _write("bootstrap_validation.json", {
        "phase": "31C",
        "results": {c["name"]: c["bootstrap"] for c in candidates},
        "generated_utc": ts,
    })
    _write("montecarlo_validation.json", {
        "phase": "31C",
        "results": {c["name"]: c["montecarlo"] for c in candidates},
        "generated_utc": ts,
    })
    _write("capture_efficiency_analysis.json", {
        "phase": "31C",
        "baseline_avg_capture": baseline_c.get("avg_capture_efficiency"),
        "by_candidate": {c["name"]: c.get("avg_capture_efficiency") for c in candidates},
        "note": "MFE used post-hoc at exit bar only — not for exit decisions",
        "generated_utc": ts,
    })
    _write("production_ranking.json", {
        "phase": "31C",
        "method": "Conservative composite — robustness and simplicity weighted over raw PF",
        "ranking_baseline": "hybrid_b_proxy",
        "production_reference_pf": baseline["profit_factor"],
        "ranked": [{
            "production_rank": r["production_rank"],
            "name": r["name"],
            "ranking_score": r["ranking_score"],
            "pf": r["metrics"]["profit_factor"],
            "pf_gain": r["pf_gain"],
            "expectancy": r["metrics"]["expectancy"],
            "max_drawdown_pct": r["metrics"]["max_drawdown_pct"],
            "robustness_score": r["robustness_score"],
            "walkforward_pass": r["walkforward"].get("walkforward_pass"),
        } for r in ranked],
        "generated_utc": ts,
    })
    _write("implementation_priority.json", {
        "phase": "31C",
        "recommended_exit": best_realworld["name"] if best_realworld else None,
        "rationale": "Best conservative score — not highest PF",
        "priority": [{
            "rank": r["production_rank"],
            "name": r["name"],
            "complexity": r.get("implementation_complexity"),
            "pf_gain": r["pf_gain"],
        } for r in ranked[:5]],
        "forbidden": ["perfect_capture", "mfe_oracle_exit", "future_bar_lookahead"],
        "generated_utc": ts,
    })

    final = {
        "phase": "31C",
        "verdict": verdict,
        "production_modified": False,
        "perfect_capture_forbidden": True,
        "candidates_evaluated": len(candidates),
        "production_baseline_pf": baseline["profit_factor"],
        "simulation_baseline_pf": sim_baseline["profit_factor"],
        "simulation_baseline_name": "hybrid_b_proxy",
        "best_realworld_exit": best_realworld["name"] if best_realworld else None,
        "best_realworld_pf": best_realworld["metrics"]["profit_factor"] if best_realworld else None,
        "best_realworld_pf_gain_vs_sim_baseline": best_realworld["pf_gain"] if best_realworld else 0,
        "best_mathematical_pf": max(c["metrics"]["profit_factor"] for c in candidates if c["name"] not in {"baseline_current", "hybrid_b_proxy"}),
        "trades_simulated": meta["trade_count"],
        "deliverables": [f"exit_candidate_{i:02d}.json" for i in range(1, 13)] + [
            "exit_candidate_13.json",
            "exit_candidate_14.json",
            "counterfactual_results.json",
            "walkforward_validation.json",
            "bootstrap_validation.json",
            "montecarlo_validation.json",
            "capture_efficiency_analysis.json",
            "production_ranking.json",
            "implementation_priority.json",
            "phase31c_final_report.json",
        ],
        "generated_utc": ts,
    }
    _write("phase31c_final_report.json", final)
    return final


def main() -> int:
    report = run_phase31c()
    print(json.dumps({
        "verdict": report["verdict"],
        "best_realworld_exit": report.get("best_realworld_exit"),
        "best_realworld_pf": report.get("best_realworld_pf"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
