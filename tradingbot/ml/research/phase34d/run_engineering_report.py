#!/usr/bin/env python3
"""Phase 34D — Engineering Decision Report (synthesizes 34A-34C + 33D)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(name: str) -> dict:
    p = ROOT / name
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def run_report() -> dict:
    r34a = _load("phase34a_final_report.json")
    r34b = _load("phase34b_final_report.json")
    r34c = _load("phase34c_final_report.json")
    r33d = _load("phase33d_final_report.json")

    r35 = _load("phase35_final_report.json")

    r36 = _load("phase36_final_report.json")
    r37 = _load("phase37_final_report.json")
    r38 = _load("phase38_final_report.json")
    r39 = _load("phase39_final_report.json")
    r40 = _load("phase40_final_report.json")
    r41 = _load("phase41_final_report.json")
    r42 = _load("phase42_final_report.json")
    r43 = _load("phase43_final_report.json")
    r44 = _load("phase44_final_report.json")
    r45 = _load("phase45_final_report.json")
    r46 = _load("phase46_final_report.json")
    r47 = _load("phase47_final_report.json")
    r48 = _load("phase48_final_report.json")
    r49 = _load("phase49_final_report.json")
    r50 = _load("phase50_final_report.json")
    r51 = _load("phase51_final_report.json")

    ml_verdict = r34a.get("verdict", "UNKNOWN")
    label_verdict = r35.get("verdict", r34b.get("verdict", "UNKNOWN"))
    filter_verdict = r34c.get("verdict", "UNKNOWN")

    raw_pf = (r34a.get("raw_ml_statistics") or {}).get("profit_factor", 0)
    exec_pf = (r34a.get("executed_statistics") or {}).get("profit_factor", 0)
    raw_wr = (r34a.get("raw_ml_statistics") or {}).get("win_rate_pct", 0)

    priorities: list[dict] = []

    if r51.get("integration_gate") == "BLOCK_PRODUCTION_INTEGRATION":
        priorities.append({
            "rank": 1,
            "action": "EXPAND_ML_CAPTURE_2021_2026_STRICT_WF",
            "reason": (
                f"Phase51 proximity={r51.get('proximity', {}).get('proximity_score')}% — "
                f"v6 PF 1.53 invalidated (bar_index bug), v7_rows={r49.get('dataset_v7_rows')}"
            ),
            "evidence_phase": "51",
        })
    elif r48.get("integration_gate") == "INTEGRATION_REVIEW_ELIGIBLE" and r50.get("gate_passed"):
        priorities.append({
            "rank": 1,
            "action": "INTEGRATION_REVIEW_ONLY",
            "reason": f"Phase48 gate={r48.get('integration_gate')}, best={r48.get('best_dataset')}",
            "evidence_phase": "48",
        })
    elif r47.get("verdict") in ("RETRAIN_READY_FOR_INTEGRATION_REVIEW", "RETRAIN_MARGINAL", "RETRAIN_IMPROVING"):
        priorities.append({
            "rank": 1,
            "action": "EXPAND_ML_SIGNAL_CAPTURE_HISTORICAL",
            "reason": (
                f"Phase47 {r47.get('verdict')}: best={r47.get('best_dataset')}, "
                f"PF={r47.get('mean_best_pf')}, v6_rows={r46.get('dataset_v6_rows')}"
            ),
            "evidence_phase": "47",
        })
    elif r46.get("verdict") in ("ML_SIGNAL_POPULATION_CAPTURED", "ML_SIGNAL_DATASET_MARGINAL"):
        priorities.append({
            "rank": 1,
            "action": "SCALE_ML_SIGNAL_DATASET",
            "reason": f"Phase46 captured {r46.get('dataset_v6_rows')} ML-aligned rows",
            "evidence_phase": "46",
        })
    elif r45.get("verdict"):
        priorities.append({
            "rank": 1,
            "action": "STRUCTURE_EVENT_LABEL_RESEARCH",
            "reason": f"Phase45 {r45.get('verdict')}: {r45.get('dataset_v5_rows')} structure rows",
            "evidence_phase": "45",
        })
    elif r44.get("integration_gate") == "INTEGRATION_REVIEW_ELIGIBLE":
        priorities.append({
            "rank": 1,
            "action": "INTEGRATION_REVIEW_ONLY",
            "reason": f"Phase44 gate={r44.get('integration_gate')}",
            "evidence_phase": "44",
        })
    elif r43.get("verdict") in ("RETRAIN_READY_FOR_INTEGRATION_REVIEW", "RETRAIN_MARGINAL", "RETRAIN_IMPROVING"):
        priorities.append({
            "rank": 1,
            "action": "CONTINUE_STRUCTURE_EVENT_LABEL_RESEARCH",
            "reason": (
                f"Phase43 {r43.get('verdict')}: best_subset={r43.get('best_subset')}, "
                f"PF={r43.get('mean_best_pf')}"
            ),
            "evidence_phase": "43",
        })
    elif r42.get("verdict") == "PARITY_OK_BIAS_IS_ROOT_CAUSE":
        priorities.append({
            "rank": 1,
            "action": "FIX_EVENT_SAMPLING_BIAS",
            "reason": f"Phase42 bias={r42.get('event_bias_verdict')}, parity={r42.get('parity_verdict')}",
            "evidence_phase": "42",
        })
    elif r39.get("verdict") in (
        "EXPANSION_READY_FOR_RETRAIN",
        "EXPANSION_IMPROVES_COVERAGE",
        "EXPANSION_MORE_ROWS_ML_STILL_WEAK",
    ):
        priorities.append({
            "rank": 1,
            "action": "FULL_TREND_MODEL_RETRAIN_ON_V3_EXPANDED",
            "reason": (
                f"Phase39 {r39.get('verdict')}: {r39.get('dataset_v3_expanded_rows')} rows, "
                f"coverage={r39.get('candle_coverage_pct')}%"
            ),
            "evidence_phase": "39",
        })
    elif r35.get("retrain_readiness", {}).get("ready"):
        priorities.append({
            "rank": 1,
            "action": "EXPAND_CANDLE_COVERAGE_AND_REBUILD_V3",
            "reason": (
                f"Labels {label_verdict}: candle coverage only "
                f"{(r35.get('candle_coverage') or {}).get('coverage_pct', 30)}%"
            ),
            "evidence_phase": "35/39",
        })
    elif label_verdict in ("LABELS_INVALID", "LABELS_NEEDS_REVIEW", "LABELS_MISALIGNED"):
        priorities.append({
            "rank": 1,
            "action": "FIX_DATASET_LABELS",
            "reason": f"Label verdict={label_verdict}",
            "evidence_phase": "34B/35",
        })

    if ml_verdict in ("ML_IS_WEAK", "ML_IS_UNUSABLE"):
        priorities.append({
            "rank": len(priorities) + 1,
            "action": "IMPROVE_ML_AFTER_LABEL_ALIGN",
            "reason": f"Raw ML verdict={ml_verdict}, PF={raw_pf}, WR={raw_wr}%",
            "evidence_phase": "34A",
        })
    elif not priorities:
        priorities.append({
            "rank": 1,
            "action": "OPTIMIZE_FILTER_LAYER",
            "reason": f"ML={ml_verdict}, filters={filter_verdict}, raw_PF={raw_pf} vs exec_PF={exec_pf}",
            "evidence_phase": "34C",
        })

    if r40.get("verdict") == "RETRAIN_READY_FOR_INTEGRATION_REVIEW":
        priorities.append({
            "rank": len(priorities) + 1,
            "action": "INTEGRATION_REVIEW_ONLY",
            "reason": f"Phase40 {r40.get('verdict')}: best_model={r40.get('best_model')}",
            "evidence_phase": "40",
        })
    elif r40.get("verdict") in ("RETRAIN_MARGINAL", "RETRAIN_IMPROVING"):
        priorities.append({
            "rank": len(priorities) + 1,
            "action": "CONTINUE_MODEL_SEARCH_ON_V3",
            "reason": f"Phase40 {r40.get('verdict')}: threshold sweep partial gain",
            "evidence_phase": "40",
        })
    elif r36.get("verdict") in ("V3_IMPROVES_OVER_V2", "RETRAIN_PROMISING"):
        priorities.append({
            "rank": len(priorities) + 1,
            "action": "FULL_TREND_MODEL_RETRAIN_ON_V3",
            "reason": f"Phase36 {r36.get('verdict')}: test PF v3={((r36.get('comparison') or {}).get('test_pf_v3'))}",
            "evidence_phase": "36",
        })
    if r37.get("verdict") == "FILTER_REMOVAL_MAY_HELP":
        priorities.append({
            "rank": len(priorities) + 1,
            "action": "MEASURE_FILTER_REMOVAL_IN_BACKTEST",
            "reason": "Phase37 simulation suggests filter removal benefit",
            "evidence_phase": "37",
        })

    if filter_verdict == "FILTERS_DESTROY_GOOD_ML":
        priorities.append({
            "rank": len(priorities) + 1,
            "action": "RELAX_HARMFUL_FILTERS",
            "reason": "Measured filters remove profitable ML trades",
            "evidence_phase": "33D+34C",
        })

    engineering_verdict = "PROCEED_TO_CONTROLLED_ENGINEERING"
    if r51.get("integration_gate") == "BLOCK_PRODUCTION_INTEGRATION":
        engineering_verdict = "BLOCK_PRODUCTION_INTEGRATION"
    elif ml_verdict == "ML_IS_UNUSABLE" and label_verdict == "LABELS_INVALID":
        engineering_verdict = "BLOCK_ENGINEERING_FIX_ROOT_CAUSE_FIRST"
    elif ml_verdict in ("ML_IS_WEAK", "ML_IS_UNUSABLE") and not r35.get("retrain_readiness", {}).get("ready"):
        engineering_verdict = "BLOCK_UNTIL_ML_OR_LABELS_FIXED"
    elif r40.get("verdict") == "RETRAIN_READY_FOR_INTEGRATION_REVIEW":
        engineering_verdict = "READY_FOR_INTEGRATION_REVIEW_ONLY"
    elif r36.get("verdict") in ("V3_IMPROVES_OVER_V2", "RETRAIN_PROMISING") or r39.get("verdict"):
        engineering_verdict = "CONTINUE_ML_RETRAIN_NOT_FILTER_TUNING"

    return {
        "now": NOW,
        "engineering_verdict": engineering_verdict,
        "phase_verdicts": {
            "34A_ml": ml_verdict,
            "34B_labels": r34b.get("verdict", "UNKNOWN"),
            "35_labels": label_verdict,
            "34C_filters": filter_verdict,
            "33D_filters": r33d.get("verdict", "UNKNOWN"),
        },
        "phase35_metrics": {
            "stored_resolve_pct": r35.get("stored_vs_resolved_match_pct"),
            "stored_production_pct": r35.get("stored_vs_production_match_pct"),
            "candle_coverage_pct": (r35.get("candle_coverage") or {}).get("coverage_pct"),
            "retrain_ready": r35.get("retrain_readiness", {}).get("ready"),
        },
        "phase36_metrics": {
            "verdict": r36.get("verdict"),
            "dataset_v3_rows": r36.get("dataset_v3_rows"),
            "test_pf_v3": (r36.get("comparison") or {}).get("test_pf_v3"),
        },
        "phase37_metrics": {
            "verdict": r37.get("verdict"),
        },
        "phase38_metrics": {
            "verdict": r38.get("verdict"),
            "mean_auc": r38.get("mean_auc"),
            "mean_pf": r38.get("mean_pf") or r38.get("mean_best_pf"),
        },
        "phase39_metrics": {
            "verdict": r39.get("verdict"),
            "dataset_v3_expanded_rows": r39.get("dataset_v3_expanded_rows"),
            "candle_coverage_pct": r39.get("candle_coverage_pct"),
        },
        "phase40_metrics": {
            "verdict": r40.get("verdict"),
            "best_model": r40.get("best_model"),
        },
        "phase41_metrics": {
            "verdict": r41.get("verdict"),
            "mean_best_pf": r41.get("mean_best_pf"),
            "integration_gate": r41.get("integration_gate"),
        },
        "phase42_metrics": {
            "verdict": r42.get("verdict"),
            "parity_verdict": r42.get("parity_verdict"),
            "event_bias_verdict": r42.get("event_bias_verdict"),
        },
        "phase43_metrics": {
            "verdict": r43.get("verdict"),
            "best_subset": r43.get("best_subset"),
            "mean_best_pf": r43.get("mean_best_pf"),
        },
        "phase44_metrics": {
            "verdict": r44.get("verdict"),
            "integration_gate": r44.get("integration_gate"),
            "blockers": r44.get("blockers"),
        },
        "phase45_metrics": {
            "verdict": r45.get("verdict"),
            "dataset_v5_rows": r45.get("dataset_v5_rows"),
        },
        "phase46_metrics": {
            "verdict": r46.get("verdict"),
            "dataset_v6_rows": r46.get("dataset_v6_rows"),
            "signals_collected": r46.get("signals_collected"),
        },
        "phase47_metrics": {
            "verdict": r47.get("verdict"),
            "best_dataset": r47.get("best_dataset"),
            "mean_best_pf": r47.get("mean_best_pf"),
        },
        "phase48_metrics": {
            "verdict": r48.get("verdict"),
            "integration_gate": r48.get("integration_gate"),
            "best_dataset": r48.get("best_dataset"),
        },
        "phase49_metrics": {
            "verdict": r49.get("verdict"),
            "dataset_v7_rows": r49.get("dataset_v7_rows"),
            "test_pf_v7": (r49.get("comparison_vs_v6_buggy") or {}).get("test_pf_v7"),
            "test_auc_v7": (r49.get("comparison_vs_v6_buggy") or {}).get("test_auc_v7"),
        },
        "phase50_metrics": {
            "verdict": r50.get("verdict"),
            "gate_passed": r50.get("gate_passed"),
            "windows_found": r50.get("windows_found"),
            "mean_pf": r50.get("mean_pf"),
        },
        "phase51_metrics": {
            "verdict": r51.get("verdict"),
            "integration_gate": r51.get("integration_gate"),
            "proximity_score": (r51.get("proximity") or {}).get("proximity_score"),
            "proximity_band": (r51.get("proximity") or {}).get("proximity_band"),
        },
        "key_metrics": {
            "raw_ml_pf": raw_pf,
            "executed_pf": exec_pf,
            "raw_ml_wr_pct": raw_wr,
            "filter_wrong_rejection_pct": r33d.get("measurement", {}).get("wrong_rejection_pct"),
        },
        "priorities": priorities,
        "blocked_until": [] if engineering_verdict in (
            "PROCEED_TO_CONTROLLED_ENGINEERING",
            "READY_FOR_INTEGRATION_REVIEW_ONLY",
        ) else [
            "threshold_changes", "filter_removal", "production_deploy",
        ],
    }


def write_all(data: dict) -> None:
    (ROOT / "engineering_next_actions.json").write_text(
        json.dumps({"timestamp_utc": data["now"], **data}, indent=2), encoding="utf-8"
    )
    (ROOT / "phase34d_final_report.json").write_text(
        json.dumps({"phase": "34D", "title": "Engineering Decision Report", **data}, indent=2),
        encoding="utf-8",
    )
    print("  wrote phase34d_final_report.json", flush=True)
    print("  wrote engineering_next_actions.json", flush=True)


def main() -> None:
    data = run_report()
    write_all(data)
    print(json.dumps({"verdict": data["engineering_verdict"], "priorities": data["priorities"]}, indent=2))


if __name__ == "__main__":
    main()
