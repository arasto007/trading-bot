"""Phase 14.7 — engine and layer contribution analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.config import PIPELINE_BASELINE, PIPELINE_FULL, PIPELINE_ROUTER
from tradingbot.ml.research.phase14_7.trade_tracker import accepted_trades


def _engine_metrics(records: list[dict[str, Any]], engine: str) -> dict[str, Any]:
    subset = [r for r in accepted_trades(records) if str(r.get("engine")) == engine]
    return trade_metrics_from_records(subset)


def _layer_blocks(records: list[dict[str, Any]]) -> dict[str, int]:
    blocks = {"confidence": 0, "risk": 0, "quality": 0}
    for r in records:
        if r.get("allowed"):
            continue
        if r.get("raw_signal") not in ("BUY", "SELL"):
            continue
        reason = str(r.get("block_reason") or "")
        if reason in blocks:
            blocks[reason] += 1
    return blocks


def analyze_engine_contribution(
    baseline_records: list[dict[str, Any]],
    router_records: list[dict[str, Any]],
    full_records: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_acc = len(accepted_trades(baseline_records))
    router_acc = len(accepted_trades(router_records))
    full_acc = len(accepted_trades(full_records))

    p99_router = _engine_metrics(router_records, "phase9_9")
    trend_router = _engine_metrics(router_records, "trend_rf_v40")
    p99_full = _engine_metrics(full_records, "phase9_9")
    trend_full = _engine_metrics(full_records, "trend_rf_v40")

    full_blocks = _layer_blocks(full_records)
    router_signals = sum(1 for r in router_records if r.get("raw_signal") in ("BUY", "SELL") and r.get("allowed"))

    return {
        "phase": "14.7",
        "phase9_9": {
            "baseline_trades": baseline_acc,
            "router_trades": p99_router["trades"],
            "full_trades": p99_full["trades"],
            "router_pf": p99_router["profit_factor"],
            "full_pf": p99_full["profit_factor"],
        },
        "trend_rf_v40": {
            "router_trades": trend_router["trades"],
            "full_trades": trend_full["trades"],
            "router_pf": trend_router["profit_factor"],
            "full_pf": trend_full["profit_factor"],
        },
        "calibration_recovery": {
            "router_accepted": router_acc,
            "full_accepted": full_acc,
            "blocked_by_confidence": full_blocks["confidence"],
            "net_vs_router": full_acc - router_acc,
        },
        "risk_adaptation": {
            "blocked_by_risk": full_blocks["risk"],
            "description": "Trades blocked after calibration by adaptive risk layer",
        },
        "quality_filter": {
            "blocked_by_quality": full_blocks["quality"],
            "description": "Trades blocked after risk by quality intelligence",
        },
        "layer_summary": {
            "baseline_to_router_delta": router_acc - baseline_acc,
            "router_to_full_delta": full_acc - router_acc,
            "router_signals_reference": router_signals,
        },
        "pipelines": {
            PIPELINE_BASELINE: baseline_acc,
            PIPELINE_ROUTER: router_acc,
            PIPELINE_FULL: full_acc,
        },
    }
