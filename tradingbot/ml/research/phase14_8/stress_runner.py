"""Phase 14.8 — market scenario filtering and stress execution."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_7.config import PIPELINE_BASELINE, PIPELINE_FULL, PIPELINE_ROUTER
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_8.config import MARKET_SCENARIOS
from tradingbot.ml.research.phase14_8.confidence_audit import audit_confidence
from tradingbot.ml.research.phase14_8.drawdown_analyzer import analyze_drawdown


def _atr_percentile(row: dict[str, Any]) -> float:
    return float(row.get("atr_percentile", row.get("volatility", 50.0)))


def filter_records_by_scenario(records: list[dict[str, Any]], scenario: str, meta: dict[str, float] | None = None) -> list[dict[str, Any]]:
    meta = meta or {}
    if scenario == "normal":
        return records
    filtered: list[dict[str, Any]] = []
    for r in records:
        regime = str(r.get("regime", ""))
        atr = float(meta.get(str(r.get("timestamp")), 50.0))
        if scenario == "high_volatility" and atr >= 70:
            filtered.append(r)
        elif scenario == "low_volatility" and atr <= 30:
            filtered.append(r)
        elif scenario == "trend_market" and regime == "TREND":
            filtered.append(r)
        elif scenario == "range_market" and regime == "RANGE":
            filtered.append(r)
        elif scenario == "news_high_atr" and atr >= 85:
            filtered.append(r)
    return filtered


def build_atr_meta(unified: pd.DataFrame) -> dict[str, float]:
    meta: dict[str, float] = {}
    for _, row in unified.iterrows():
        ts = str(pd.to_datetime(row["timestamp"], utc=True))
        meta[ts] = float(row.get("atr_percentile", row.get("volatility", 50.0)))
    return meta


def run_scenario_stress(
    baseline_records: list[dict[str, Any]],
    router_records: list[dict[str, Any]],
    full_records: list[dict[str, Any]],
    *,
    atr_meta: dict[str, float] | None = None,
    stride: int = 5,
    scenarios: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    names = scenarios or MARKET_SCENARIOS
    out: dict[str, Any] = {"phase": "14.8", "scenarios": {}}

    for scenario in names:
        b = filter_records_by_scenario(baseline_records, scenario, atr_meta)
        r = filter_records_by_scenario(router_records, scenario, atr_meta)
        f = filter_records_by_scenario(full_records, scenario, atr_meta)
        full_metrics = analyze_performance(f, stride=stride)
        out["scenarios"][scenario] = {
            "baseline": analyze_performance(b, stride=stride),
            "router": analyze_performance(r, stride=stride),
            "full": full_metrics,
            "drawdown": analyze_drawdown(f),
            "confidence": audit_confidence(f),
            "quality_distribution": _quality_dist(f),
            "risk_distribution": _risk_dist(f),
            "positive_expectancy": float(full_metrics.get("expectancy", 0)) > 0,
        }
    return out


def _quality_dist(records: list[dict[str, Any]]) -> dict[str, float]:
    vals = [float(r["quality_score"]) for r in records if r.get("allowed") and r.get("quality_score")]
    if not vals:
        return {"mean": 0.0, "min": 0.0, "max": 0.0}
    return {"mean": round(sum(vals) / len(vals), 4), "min": round(min(vals), 4), "max": round(max(vals), 4)}


def _risk_dist(records: list[dict[str, Any]]) -> dict[str, float]:
    vals = [float(r["risk_percent"]) for r in records if r.get("allowed") and r.get("risk_percent")]
    if not vals:
        return {"mean": 0.0, "min": 0.0, "max": 0.0}
    return {"mean": round(sum(vals) / len(vals), 4), "min": round(min(vals), 4), "max": round(max(vals), 4)}


def summarize_pipelines(
    baseline_records: list[dict[str, Any]],
    router_records: list[dict[str, Any]],
    full_records: list[dict[str, Any]],
    *,
    stride: int = 5,
) -> dict[str, Any]:
    return {
        PIPELINE_BASELINE: analyze_performance(baseline_records, stride=stride),
        PIPELINE_ROUTER: analyze_performance(router_records, stride=stride),
        PIPELINE_FULL: analyze_performance(full_records, stride=stride),
    }
