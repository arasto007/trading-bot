"""Phase 16C — read-only threshold simulation (analysis only)."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase16c.config import SIMULATION_THRESHOLDS


def simulate_thresholds(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Simulate alternate RF thresholds without modifying production.
    PF/expectancy are proxy estimates from probability margin only.
    """
    rule_pass = [r for r in records if r.get("rule_direction") in ("BUY", "SELL")]
    results: dict[str, Any] = {}

    baseline_40 = sum(1 for r in rule_pass if r["probability"] >= 0.40)

    for th in SIMULATION_THRESHOLDS:
        actionable = [r for r in rule_pass if r["probability"] >= th]
        extra_vs_40 = len(actionable) - baseline_40 if th < 0.40 else 0
        margins = [r["probability"] - th for r in actionable]
        mean_margin = float(np.mean(margins)) if margins else 0.0

        # Proxy PF: ratio of bars above threshold+0.05 vs below threshold
        strong = sum(1 for r in rule_pass if r["probability"] >= th + 0.05)
        weak = len(actionable) - strong
        pf_proxy = round(strong / max(weak, 1), 4) if actionable else 0.0
        expectancy_proxy = round(mean_margin * len(actionable) / max(len(rule_pass), 1), 6)

        results[str(th)] = {
            "threshold": th,
            "actionable_signals": len(actionable),
            "extra_vs_production_0.40": max(0, extra_vs_40) if th < 0.40 else 0,
            "actionable_rate": round(len(actionable) / max(len(rule_pass), 1), 6),
            "mean_probability_margin": round(mean_margin, 6),
            "pf_proxy": pf_proxy,
            "expectancy_proxy": expectancy_proxy,
        }

    return {
        "simulation_only": True,
        "production_unchanged": True,
        "rule_pass_bars": len(rule_pass),
        "thresholds": results,
        "recommend_threshold_change": False,
        "note": "Proxy metrics only; no production threshold modification recommended from simulation alone.",
    }


def build_throughput_analysis(funnel: dict[str, Any], rf_dist: dict[str, Any], rule_stats: dict[str, Any]) -> dict[str, Any]:
    fc = funnel.get("funnel_counts", {})
    trend = fc.get("trend_bars", 0) or 1
    rule_pass = fc.get("rule_pass", 0)
    rf_pass = fc.get("rf_pass", 0)
    kernel = fc.get("kernel_output", 0)

    rule_drop = trend - rule_pass
    rf_drop = rule_pass - rf_pass
    post_rf_drop = rf_pass - kernel

    return {
        "trend_bars": trend,
        "throughput_kernel_rate": round(kernel / trend, 6),
        "bottleneck_stages": {
            "rule_filter_removed": rule_drop,
            "rf_filter_removed": rf_drop,
            "post_rf_pipeline_removed": post_rf_drop,
        },
        "rule_share_of_loss": round(rule_drop / max(trend - kernel, 1), 4),
        "rf_share_of_loss": round(rf_drop / max(trend - kernel, 1), 4),
        "max_probability": rf_dist.get("stats", {}).get("max", 0.0),
        "p99_probability": rf_dist.get("stats", {}).get("p99", 0.0),
        "rules_restrictive_before_rf": rule_stats.get("rules_restrictive_before_rf", False),
        "primary_engine_bottleneck": (
            "RULE" if rule_drop > rf_drop * 1.5
            else "RF" if rf_drop > rule_drop * 1.5
            else "MIXED"
        ),
    }
