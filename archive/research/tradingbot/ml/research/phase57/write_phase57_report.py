"""Phase 57 — combined report writer and status updates (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]


def _estimate_proximity(tq_data: dict, trend_data: dict) -> dict[str, Any]:
    from tradingbot.ml.research.phase51.profitability_score import profitability_proximity

    stable = _stable_threshold(trend_data)
    trend_mean_pf = float(stable.get("mean_pf") or trend_data.get("mean_pf_best_per_year") or 0)
    trend_mean_auc = float(trend_data.get("mean_auc") or 0)
    bypass_pf = float((tq_data.get("pf_proxy_bypass_path") or {}).get("pf_proxy") or 0)
    windows = int(trend_data.get("windows") or 0)
    windows_pf_13 = sum(
        1 for w in (trend_data.get("per_year") or [])
        if float(w.get("best_pf") or 0) >= 1.3
    )

    prox = profitability_proximity(
        strict_gate_passed=bool(trend_data.get("gate_passed")),
        mean_pf=max(trend_mean_pf, bypass_pf * 0.5),
        mean_auc=trend_mean_auc,
        windows_count=windows,
        windows_pf_above_1_3=windows_pf_13,
        raw_ml_pf=bypass_pf,
        executed_pf=0.0,
        label_prod_match_pct=100.0,
        v7_rows=int(trend_data.get("rows_trend") or 81035),
    )
    return prox


def _stable_threshold(trend_data: dict) -> dict[str, Any]:
    """Pick threshold with best mean PF among those covering all WF windows."""
    windows = int(trend_data.get("windows") or 0)
    best: dict[str, Any] = {}
    for row in trend_data.get("threshold_summary") or []:
        if int(row.get("windows_with_min_trades") or 0) >= windows and windows > 0:
            if not best or float(row.get("mean_pf") or 0) > float(best.get("mean_pf") or 0):
                best = row
    return best or (trend_data.get("best_overall") or {})


def _recommendation(tq_data: dict, trend_data: dict) -> str:
    bypass_capture = float((tq_data.get("aggregate") or {}).get("bypass_capture_rate_pct") or 0)
    bypass_pf = float((tq_data.get("pf_proxy_bypass_path") or {}).get("pf_proxy") or 0)
    stable = _stable_threshold(trend_data)
    stable_thr = stable.get("threshold")
    stable_pf = float(stable.get("mean_pf") or 0)

    if bypass_pf < 1.0:
        return (
            f"Highest ROI: do NOT relax TradeQuality — bypass releases {bypass_capture:.0f}% of signals "
            f"but PF proxy is only {bypass_pf:.2f}. Next phase: TREND-only RF on top-5 features "
            f"at threshold {stable_thr} (stable mean PF {stable_pf:.2f} across all WF windows)."
        )
    if stable_pf >= 1.0 and stable_thr is not None:
        return (
            f"Highest ROI: TREND-only model threshold {stable_thr} (stable mean PF {stable_pf:.2f}) "
            "in research/shadow — validate before any production filter change."
        )
    return (
        "Highest ROI: continue TREND-subset ML with expanded features; "
        "production TradeQuality unchanged until bypass PF proxy exceeds 1.0."
    )


def write_phase57_report(tq_data: dict[str, Any], trend_data: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proximity = _estimate_proximity(tq_data, trend_data)
    recommendation = _recommendation(tq_data, trend_data)

    report = {
        "phase": "57",
        "title": "TradeQuality Simulation & TREND Deep Dive",
        "title_fa": "شبیه‌سازی TradeQuality و بررسی عمیق TREND",
        "timestamp_utc": now,
        "verdict": trend_data.get("verdict", "INCOMPLETE"),
        "research_only": True,
        "trade_quality_simulation": {
            "verdict": tq_data.get("verdict"),
            "aggregate": tq_data.get("aggregate"),
            "pf_proxy_current_path": tq_data.get("pf_proxy_current_path"),
            "pf_proxy_bypass_path": tq_data.get("pf_proxy_bypass_path"),
            "per_cache": tq_data.get("per_cache"),
        },
        "trend_regime_deep_dive": {
            "verdict": trend_data.get("verdict"),
            "model": trend_data.get("model"),
            "features_used": trend_data.get("features_used"),
            "thresholds_tested": trend_data.get("thresholds_tested"),
            "best_overall": trend_data.get("best_overall"),
            "best_stable_threshold": _stable_threshold(trend_data),
            "threshold_summary": trend_data.get("threshold_summary"),
            "mean_pf_best_per_year": trend_data.get("mean_pf_best_per_year"),
            "mean_auc": trend_data.get("mean_auc"),
            "per_year": trend_data.get("per_year"),
            "rows_trend": trend_data.get("rows_trend"),
        },
        "proximity_update": proximity,
        "recommendation": recommendation,
    }

    (ROOT / "phase57_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase57_final_report.json", flush=True)

    _update_engineering_status(report, proximity)
    _update_treatment_roadmap(report)


def _update_engineering_status(report: dict, proximity: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    agg = report.get("trade_quality_simulation", {}).get("aggregate") or {}
    trend = report.get("trend_regime_deep_dive") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "TREATMENT_PHASE_57_COMPLETE"
    status["proximity_score"] = proximity.get("proximity_score")
    status["proximity_band"] = proximity.get("proximity_band")
    status["how_close_pct"] = proximity.get("proximity_score")
    status["current_treatment_phase"] = "57"
    status["next_step"] = report.get("recommendation", "")

    status.setdefault("treatment_phases", {})["57"] = {
        "status": "COMPLETE",
        "track": "B",
        "verdict": report.get("verdict"),
        "report": "phase57_final_report.json",
        "sub_phases": {
            "57A": "trade_quality_simulation",
            "57B": "trend_regime_deep_dive",
        },
    }
    status["phase57_summary"] = {
        "bypass_capture_rate_pct": agg.get("bypass_capture_rate_pct"),
        "bypass_pf_proxy": (report.get("trade_quality_simulation") or {})
            .get("pf_proxy_bypass_path", {}).get("pf_proxy"),
        "trend_best_threshold": (trend.get("best_overall") or {}).get("threshold"),
        "trend_best_mean_pf": (trend.get("best_overall") or {}).get("mean_pf"),
        "trend_stable_threshold": (trend.get("best_stable_threshold") or {}).get("threshold"),
        "trend_stable_mean_pf": (trend.get("best_stable_threshold") or {}).get("mean_pf"),
        "trend_mean_pf_per_year": trend.get("mean_pf_best_per_year"),
    }

    if "58" in status.get("treatment_phases", {}):
        status["treatment_phases"]["58"]["status"] = "BLOCKED"
        status["treatment_phases"]["58"]["reason"] = "Phase 56 re-gate failed; phase57 research complete"

    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_treatment_roadmap(report: dict) -> None:
    path = ROOT / "TREATMENT_ROADMAP.json"
    if not path.is_file():
        return
    roadmap = json.loads(path.read_text(encoding="utf-8"))

    for phase in roadmap.get("phases", []):
        if str(phase.get("phase")) == "57":
            phase["status"] = "COMPLETE"
            phase["name_en"] = "TradeQuality Simulation & TREND Deep Dive"
            phase["name_fa"] = "شبیه‌سازی TradeQuality و بررسی عمیق TREND"
            phase["objective"] = (
                "Counterfactual TradeQuality bypass on phase46 caches; "
                "TREND-only walk-forward threshold sweep on v7."
            )
            phase["outputs"] = [
                "phase57_final_report.json",
                "tradingbot/ml/research/phase57/artifacts/trade_quality_simulation.json",
                "tradingbot/ml/research/phase57/artifacts/trend_regime_deep_dive.json",
            ]
            phase["runner"] = "tradingbot/ml/research/phase57/trade_quality_simulation.py"
            phase["track"] = "B"
            phase["verdict"] = report.get("verdict")
            break

    pipeline = roadmap.setdefault("pipeline", {})
    pipeline["current_phase"] = "57"
    if "57" not in pipeline.get("execution_order", []):
        pipeline.setdefault("execution_order", []).append("57")

    roadmap["updated_utc"] = report["timestamp_utc"]
    path.write_text(json.dumps(roadmap, indent=2), encoding="utf-8")
    print("  updated TREATMENT_ROADMAP.json", flush=True)
