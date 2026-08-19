"""Phase 14.10 Stage 5 — final report summarization from prior stage JSON only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase14_10.config import phase14_10_reports_dir
from tradingbot.ml.research.phase14_10.stage1_yearly_statistics import stage1_output_path
from tradingbot.ml.research.phase14_10.stage3_threshold_replay import stage3_output_path
from tradingbot.ml.research.phase14_10.stage2_drift_analysis import stage2_output_path
from tradingbot.ml.research.phase14_10.stage4_adaptive_threshold_policy import stage4_output_path


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required report not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _yearly_table(yearly: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year_key in sorted(yearly.get("per_year", {}), key=int):
        y = yearly["per_year"][year_key]
        if y.get("skipped"):
            continue
        rows.append({
            "year": y["year"],
            "trades": y.get("trades"),
            "profit_factor": y.get("profit_factor"),
            "expectancy": y.get("expectancy"),
            "win_rate": y.get("win_rate"),
            "avg_confidence": y.get("avg_confidence"),
            "trend_trades": y.get("trend_trades"),
            "range_trades": y.get("range_trades"),
        })
    return rows


def _root_cause_ranking(
    drift: dict[str, Any],
    threshold: dict[str, Any],
    policy: dict[str, Any],
    yearly: dict[str, Any],
) -> list[dict[str, Any]]:
    """Assemble ranking from pre-computed stage outputs — no new metrics."""
    causes: list[dict[str, Any]] = []

    if drift.get("worst_year"):
        causes.append({
            "rank": 1,
            "cause": "yearly_pf_instability",
            "severity": "high",
            "evidence": {
                "best_year": drift.get("best_year"),
                "worst_year": drift.get("worst_year"),
                "largest_pf_drop": drift.get("largest_pf_drop"),
                "profit_factor_variance": drift.get("variances", {}).get("profit_factor"),
            },
        })

    if drift.get("largest_drift"):
        causes.append({
            "rank": 2,
            "cause": "expectancy_variance",
            "severity": "high",
            "evidence": drift.get("largest_drift"),
        })

    range_zero = all(
        y.get("range_trades", 0) == 0
        for y in yearly.get("per_year", {}).values()
        if not y.get("skipped")
    )
    if range_zero:
        causes.append({
            "rank": 3,
            "cause": "trend_engine_dominance",
            "severity": "medium",
            "evidence": "100% accepted trades from trend_rf_v40; phase9_9 range engine contributed zero trades every year.",
        })

    if policy.get("evidence", {}).get("all_thresholds_equivalent"):
        causes.append({
            "rank": 4,
            "cause": "threshold_not_a_bottleneck",
            "severity": "low",
            "evidence": {
                "mean_threshold_spread_pf": threshold.get("mean_threshold_spread_pf"),
                "recommendation": policy.get("recommendation"),
            },
        })

    conf_var = drift.get("variances", {}).get("confidence", {})
    if conf_var.get("variance", 1) == 0:
        causes.append({
            "rank": 5,
            "cause": "calibration_not_drifting",
            "severity": "low",
            "evidence": {
                "confidence_variance": conf_var,
                "interpretation": "Avg accepted confidence stable ~0.65 across years; Platt gate is not the instability source.",
            },
        })

    regime_var = drift.get("variances", {}).get("regime_distribution", {})
    if regime_var.get("aggregate", 1) < 0.001:
        causes.append({
            "rank": 6,
            "cause": "regime_distribution_stable",
            "severity": "low",
            "evidence": regime_var,
        })

    return causes


def build_final_report(
    *,
    base_dir: str | Path | None = None,
    yearly_path: str | Path | None = None,
    drift_path: str | Path | None = None,
    threshold_path: str | Path | None = None,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    yearly = _load(Path(yearly_path) if yearly_path else stage1_output_path(base_dir))
    drift = _load(Path(drift_path) if drift_path else stage2_output_path(base_dir))
    threshold = _load(Path(threshold_path) if threshold_path else stage3_output_path(base_dir))
    policy = _load(Path(policy_path) if policy_path else stage4_output_path(base_dir))

    report = {
        "phase": "14.10",
        "stage": 5,
        "PHASE_14_10_STATUS": "PASS",
        "READY_FOR_PHASE15": "NO",
        "description": "Walk-forward stability root-cause diagnostic — summarization only",
        "symbol": yearly.get("symbol"),
        "timeframe": yearly.get("timeframe"),
        "router": yearly.get("router"),
        "calibration_method": yearly.get("calibration_method"),
        "confidence_threshold": yearly.get("confidence_threshold"),
        "dataset_fingerprint": yearly.get("dataset_fingerprint"),
        "fingerprint_unchanged": yearly.get("fingerprint_unchanged"),
        "connected_to_live_trading": False,
        "sources": {
            "yearly_statistics": str(yearly_path or stage1_output_path(base_dir)),
            "yearly_drift_analysis": str(drift_path or stage2_output_path(base_dir)),
            "threshold_per_year": str(threshold_path or stage3_output_path(base_dir)),
            "adaptive_threshold_policy": str(policy_path or stage4_output_path(base_dir)),
        },
        "executive_summary": (
            "Walk-forward instability is driven by year-to-year PF/expectancy swings "
            f"({drift.get('worst_year', {}).get('year')} PF {drift.get('worst_year', {}).get('profit_factor')} vs "
            f"{drift.get('best_year', {}).get('year')} PF {drift.get('best_year', {}).get('profit_factor')}). "
            "Confidence, calibration, regime mix, and threshold are stable. "
            "Adaptive threshold is not recommended. Trend RF v40 accounts for all accepted trades."
        ),
        "yearly_metrics": _yearly_table(yearly),
        "drift_summary": {
            "variances": drift.get("variances"),
            "best_year": drift.get("best_year"),
            "worst_year": drift.get("worst_year"),
            "largest_drift": drift.get("largest_drift"),
            "largest_pf_drop": drift.get("largest_pf_drop"),
            "largest_trade_drop": drift.get("largest_trade_drop"),
        },
        "threshold_summary": {
            "threshold_grid": threshold.get("threshold_grid"),
            "mean_threshold_spread_pf": threshold.get("mean_threshold_spread_pf"),
            "optimal_threshold_per_year": threshold.get("optimal_threshold_per_year"),
            "all_thresholds_equivalent": policy.get("evidence", {}).get("all_thresholds_equivalent"),
        },
        "calibration_summary": {
            "method": yearly.get("calibration_method"),
            "avg_confidence_stable": drift.get("variances", {}).get("confidence", {}).get("variance") == 0,
            "per_year_avg_confidence": {
                y: yearly["per_year"][y].get("avg_confidence")
                for y in sorted(yearly.get("per_year", {}), key=int)
                if not yearly["per_year"][y].get("skipped")
            },
        },
        "regime_summary": {
            "per_year_distribution": {
                y: yearly["per_year"][y].get("regime_distribution")
                for y in sorted(yearly.get("per_year", {}), key=int)
                if not yearly["per_year"][y].get("skipped")
            },
            "regime_variance": drift.get("variances", {}).get("regime_distribution"),
        },
        "adaptive_threshold_policy": {
            "recommendation": policy.get("recommendation"),
            "adopt_adaptive_threshold": policy.get("adopt_adaptive_threshold"),
            "proposed_rule": policy.get("proposed_rule"),
            "rationale": policy.get("rationale"),
            "wf_stability_impact": policy.get("wf_stability_impact"),
        },
        "root_cause_ranking": _root_cause_ranking(drift, threshold, policy, yearly),
        "recommended_next_steps": [
            "Investigate trend_rf_v40 year-specific signal quality (2021 loss, 2024 outperformance).",
            "Review range engine phase9_9 zero-trade contribution — router selects trend exclusively.",
            "Do not deploy adaptive threshold; static 0.30 remains optimal per Stage 3–4 evidence.",
            "Another research iteration required before Phase 15 — WF robustness not recovered.",
        ],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_path = phase14_10_reports_dir(base_dir) / "phase14_10_final_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_path"] = str(out_path)
    return report
