"""Phase 14.10 Stage 4 — adaptive threshold policy from Stage 1+3 JSON only."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase14_10.config import BASELINE_THRESHOLD, phase14_10_reports_dir
from tradingbot.ml.research.phase14_10.stage1_yearly_statistics import stage1_output_path
from tradingbot.ml.research.phase14_10.stage3_threshold_replay import stage3_output_path


def stage4_output_path(base_dir: str | Path | None = None) -> Path:
    return phase14_10_reports_dir(base_dir) / "adaptive_threshold_policy.json"


def _proposed_regime_threshold(trend_pct: float, range_pct: float) -> float:
    """Research rule aligned with Phase 14.10 adaptive threshold research."""
    if trend_pct >= 0.60:
        return 0.28
    if range_pct >= 0.40:
        return 0.35
    return BASELINE_THRESHOLD


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required input not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_adaptive_threshold_policy(
    *,
    base_dir: str | Path | None = None,
    yearly_stats_path: str | Path | None = None,
    threshold_path: str | Path | None = None,
) -> dict[str, Any]:
    stats_path = Path(yearly_stats_path) if yearly_stats_path else stage1_output_path(base_dir)
    th_path = Path(threshold_path) if threshold_path else stage3_output_path(base_dir)

    yearly = _load_json(stats_path)
    threshold = _load_json(th_path)

    static_th = float(yearly.get("confidence_threshold", BASELINE_THRESHOLD))
    per_year_policy: dict[str, Any] = {}
    pf_deltas: list[float] = []
    trade_deltas: list[int] = []
    proposed_differs_from_static = False

    for year_key in sorted(yearly.get("per_year", {}), key=int):
        ys = yearly["per_year"][year_key]
        ts = threshold.get("per_year", {}).get(year_key, {})
        if ys.get("skipped") or ts.get("skipped"):
            per_year_policy[year_key] = {"year": int(year_key), "skipped": True}
            continue

        regime = ys.get("regime_distribution", {})
        trend_pct = float(regime.get("TREND", 0.0))
        range_pct = float(regime.get("RANGE", 0.0))
        proposed_th = _proposed_regime_threshold(trend_pct, range_pct)
        if proposed_th != static_th:
            proposed_differs_from_static = True

        th_results = ts.get("thresholds", {})
        static_metrics = th_results.get(str(static_th), {})
        proposed_metrics = th_results.get(str(proposed_th), static_metrics)
        optimal_th = float(ts.get("best_threshold_by_pf", static_th))

        pf_delta = round(
            float(proposed_metrics.get("profit_factor", 0)) - float(static_metrics.get("profit_factor", 0)),
            4,
        )
        trade_delta = int(proposed_metrics.get("trades", 0)) - int(static_metrics.get("trades", 0))
        pf_deltas.append(pf_delta)
        trade_deltas.append(trade_delta)

        per_year_policy[year_key] = {
            "year": int(year_key),
            "skipped": False,
            "trend_pct": trend_pct,
            "range_pct": range_pct,
            "static_threshold": static_th,
            "proposed_adaptive_threshold": proposed_th,
            "optimal_threshold_by_replay": optimal_th,
            "static_pf": static_metrics.get("profit_factor"),
            "proposed_pf": proposed_metrics.get("profit_factor"),
            "pf_delta_vs_static": pf_delta,
            "trade_delta_vs_static": trade_delta,
            "threshold_sensitive": float(ts.get("threshold_spread_pf", 0)) > 0,
        }

    mean_spread = float(threshold.get("mean_threshold_spread_pf", 0))
    all_equivalent = mean_spread <= 1e-9 and all(d == 0 for d in pf_deltas)
    any_improvement = any(d > 0 for d in pf_deltas)

    if all_equivalent:
        recommendation = "keep_static"
        adopt_adaptive = False
        rationale = (
            "Stage 3 replay shows identical PF/trades across thresholds 0.25–0.40 for every year. "
            "Accepted-trade confidence (~0.65) sits above all tested gates; risk/quality bound the set. "
            "Adaptive threshold would not change outcomes or improve walk-forward stability."
        )
    elif any_improvement and proposed_differs_from_static:
        recommendation = "use_adaptive_threshold"
        adopt_adaptive = True
        rationale = (
            "Per-year replay shows threshold sensitivity; regime-based rule improves PF vs static baseline."
        )
    else:
        recommendation = "keep_static"
        adopt_adaptive = False
        rationale = (
            "Threshold replay does not support switching from static policy; adaptive rule shows no PF gain."
        )

    policy_rule = (
        "IF trend_pct >= 60% THEN threshold=0.28 "
        "ELIF range_pct >= 40% THEN threshold=0.35 "
        f"ELSE threshold={static_th}"
    )

    result = {
        "phase": "14.10",
        "stage": 4,
        "research_only": True,
        "description": "Adaptive threshold policy recommendation from Stage 1+3 evidence",
        "sources": {
            "yearly_statistics": str(stats_path),
            "threshold_per_year": str(th_path),
        },
        "symbol": yearly.get("symbol"),
        "timeframe": yearly.get("timeframe"),
        "static_threshold": static_th,
        "recommendation": recommendation,
        "adopt_adaptive_threshold": adopt_adaptive,
        "proposed_rule": policy_rule,
        "evidence": {
            "mean_threshold_spread_pf": mean_spread,
            "all_thresholds_equivalent": all_equivalent,
            "optimal_threshold_per_year": threshold.get("optimal_threshold_per_year", {}),
            "max_pf_delta_adaptive_vs_static": max(pf_deltas) if pf_deltas else 0.0,
            "mean_pf_delta_adaptive_vs_static": round(statistics.mean(pf_deltas), 4) if pf_deltas else 0.0,
            "max_trade_delta_adaptive_vs_static": max(trade_deltas) if trade_deltas else 0,
        },
        "per_year_policy": per_year_policy,
        "rationale": rationale,
        "wf_stability_impact": "none" if all_equivalent else "unknown_requires_stage5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_path = stage4_output_path(base_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["output_path"] = str(out_path)
    return result
