#!/usr/bin/env python3
"""Phase 34C — Filter Marginal Value Synthesis (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(name: str) -> dict | None:
    p = ROOT / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _pf(rs: list[float]) -> float:
    w = sum(x for x in rs if x > 0)
    l = abs(sum(x for x in rs if x < 0))
    return round(w / l, 4) if l > 0 else (2.0 if w > 0 else 0.0)


def run_audit() -> dict:
    d33 = _load_json("phase33d_final_report.json") or _load_json("filter_truth_table.json")
    d34a = _load_json("phase34a_final_report.json")
    filter_truth = {}
    if d33:
        filter_truth = d33.get("filter_truth_summary") or d33.get("per_filter") or {}

    raw_pf = float((d34a or {}).get("raw_ml_statistics", {}).get("profit_factor", 0))
    exec_pf = float((d34a or {}).get("executed_statistics", {}).get("profit_factor", 0))

    marginal: list[dict] = []
    for filt, stats in filter_truth.items():
        if not isinstance(stats, dict):
            continue
        edge_lost = float(stats.get("edge_lost_r", 0))
        fnr = float(stats.get("false_negative_rate", stats.get("false_negative_pct", 0) / 100))
        prec = float(stats.get("precision", 0))
        n = int(stats.get("rejected_trades", 0))
        category = "HARMFUL" if fnr >= 0.3 and edge_lost > 10 else (
            "PROFITABLE" if prec >= 0.7 and fnr < 0.15 else "NEUTRAL"
        )
        marginal.append({
            "filter": filt,
            "rejected_trades": n,
            "precision": prec,
            "false_negative_rate": fnr,
            "edge_lost_r": edge_lost,
            "category": category,
            "recommendation": "MEASURE_ONLY",
        })

    marginal.sort(key=lambda x: x["edge_lost_r"], reverse=True)

    overlap_groups = {
        "confidence_stack": ["DecisionOrchestrator", "Calibration", "TradeQuality"],
        "volatility_stack": ["ATR Filter", "AdaptiveRisk"],
        "trend_strength_stack": ["ADX Filter", "RSI Filter", "TradeQuality"],
        "risk_stack": ["RiskGate", "Cooldown", "Daily Loss Limit", "Max Positions", "Friday Gate"],
    }

    harmful = [m for m in marginal if m["category"] == "HARMFUL"]
    profitable = [m for m in marginal if m["category"] == "PROFITABLE"]

    verdict = "FILTERS_MIXED"
    if len(harmful) >= 3 and raw_pf > exec_pf * 1.5:
        verdict = "FILTERS_MASK_WEAK_ML"
    elif raw_pf >= 1.2 and exec_pf < 1.0:
        verdict = "FILTERS_DESTROY_GOOD_ML"
    elif raw_pf < 0.9 and exec_pf >= raw_pf:
        verdict = "FILTERS_COMPENSATE_WEAK_ML"
    elif raw_pf >= 1.0 and exec_pf >= 0.8:
        verdict = "ML_AND_FILTERS_BOTH_CONTRIBUTE"

    return {
        "now": NOW,
        "verdict": verdict,
        "raw_ml_pf": raw_pf,
        "executed_pf": exec_pf,
        "filter_marginal": marginal,
        "overlap_groups": overlap_groups,
        "harmful_filters": harmful,
        "profitable_filters": profitable,
        "top_edge_destroyers": marginal[:5],
    }


def write_all(data: dict) -> None:
    def w(name: str, payload: dict) -> None:
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    w("filter_marginal_value.json", {"timestamp_utc": data["now"], "filters": data["filter_marginal"]})
    w("phase34c_final_report.json", {
        "phase": "34C",
        "title": "Filter Marginal Value Synthesis",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "raw_ml_pf": data["raw_ml_pf"],
        "executed_pf": data["executed_pf"],
        "harmful_filters": data["harmful_filters"],
        "profitable_filters": data["profitable_filters"],
        "overlap_groups": data["overlap_groups"],
        "deliverables": ["filter_marginal_value.json", "phase34c_final_report.json"],
    })


def main() -> None:
    data = run_audit()
    write_all(data)
    print(json.dumps({"verdict": data["verdict"], "raw_pf": data["raw_ml_pf"], "exec_pf": data["executed_pf"]}, indent=2))


if __name__ == "__main__":
    main()
