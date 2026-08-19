"""Phase 14.10 Stage 2 — yearly drift analysis from Stage 1 JSON only."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase14_10.config import phase14_10_reports_dir


def stage1_input_path(base_dir: str | Path | None = None) -> Path:
    return phase14_10_reports_dir(base_dir) / "yearly_statistics.json"


def stage2_output_path(base_dir: str | Path | None = None) -> Path:
    return phase14_10_reports_dir(base_dir) / "yearly_drift_analysis.json"


def _active_years(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        v for v in payload.get("per_year", {}).values()
        if not v.get("skipped")
    ]


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return round(float(statistics.pvariance(values)), 6)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return round(float(statistics.pstdev(values)), 6)


def _regime_variance(years: list[dict[str, Any]]) -> dict[str, float]:
    regimes = ("TREND", "RANGE", "HIGH_VOLATILITY", "NO_TRADE")
    out: dict[str, float] = {}
    for regime in regimes:
        vals = [
            float(y.get("regime_distribution", {}).get(regime, 0.0))
            for y in years
        ]
        out[regime] = _variance(vals)
    out["aggregate"] = round(sum(out.values()) / len(regimes), 6)
    return out


def _year_over_year_drops(
    years: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, Any] | None:
    ordered = sorted(years, key=lambda y: int(y["year"]))
    if len(ordered) < 2:
        return None
    worst_drop = 0.0
    worst: dict[str, Any] | None = None
    for prev, curr in zip(ordered, ordered[1:]):
        drop = float(prev[key]) - float(curr[key])
        if drop > worst_drop:
            worst_drop = drop
            worst = {
                "from_year": int(prev["year"]),
                "to_year": int(curr["year"]),
                "from_value": round(float(prev[key]), 4),
                "to_value": round(float(curr[key]), 4),
                "drop": round(drop, 4),
            }
    return worst


def _cv(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    std = statistics.pstdev(values)
    if abs(mean) < 1e-9:
        return round(std, 6)
    return round(std / abs(mean), 6)


def _largest_drift(years: list[dict[str, Any]], variances: dict[str, Any]) -> dict[str, Any]:
    pf = [float(y["profit_factor"]) for y in years]
    exp = [float(y["expectancy"]) for y in years]
    tr = [float(y["trades"]) for y in years]
    conf = [float(y["avg_confidence"]) for y in years]
    risk = [float(y["avg_risk"]) for y in years]
    qual = [float(y["avg_quality"]) for y in years]
    regime_cvs = [
        _cv([float(y.get("regime_distribution", {}).get(r, 0.0)) for y in years])
        for r in ("TREND", "RANGE", "HIGH_VOLATILITY", "NO_TRADE")
    ]

    metric_map = {
        "profit_factor": _cv(pf),
        "expectancy": _cv(exp),
        "trades": _cv(tr),
        "avg_confidence": _cv(conf),
        "avg_risk": _cv(risk),
        "avg_quality": _cv(qual),
        "regime_distribution": max(regime_cvs) if regime_cvs else 0.0,
    }
    metric = max(metric_map, key=metric_map.get)
    variance_key = {
        "profit_factor": "profit_factor",
        "expectancy": "expectancy",
        "trades": "trades",
        "avg_confidence": "confidence",
        "avg_risk": "risk",
        "avg_quality": "quality",
    }.get(metric)
    return {
        "metric": metric,
        "coefficient_of_variation": metric_map[metric],
        "variance": (
            variances[variance_key]["variance"]
            if variance_key
            else variances["regime_distribution"]["aggregate"]
        ),
        "interpretation": "Highest relative year-to-year spread (CV) across Stage 1 metrics.",
    }


def analyze_yearly_drift(
    *,
    base_dir: str | Path | None = None,
    input_path: str | Path | None = None,
) -> dict[str, Any]:
    in_path = Path(input_path) if input_path else stage1_input_path(base_dir)
    if not in_path.is_file():
        raise FileNotFoundError(f"Stage 1 output not found: {in_path}")

    stage1 = json.loads(in_path.read_text(encoding="utf-8"))
    years = _active_years(stage1)
    if not years:
        raise ValueError("No active years in yearly_statistics.json")

    pf_vals = [float(y["profit_factor"]) for y in years]
    exp_vals = [float(y["expectancy"]) for y in years]
    trade_vals = [float(y["trades"]) for y in years]
    conf_vals = [float(y["avg_confidence"]) for y in years]
    risk_vals = [float(y["avg_risk"]) for y in years]
    qual_vals = [float(y["avg_quality"]) for y in years]

    variances = {
        "profit_factor": {"variance": _variance(pf_vals), "std": _std(pf_vals)},
        "expectancy": {"variance": _variance(exp_vals), "std": _std(exp_vals)},
        "trades": {"variance": _variance(trade_vals), "std": _std(trade_vals)},
        "confidence": {"variance": _variance(conf_vals), "std": _std(conf_vals)},
        "risk": {"variance": _variance(risk_vals), "std": _std(risk_vals)},
        "quality": {"variance": _variance(qual_vals), "std": _std(qual_vals)},
        "regime_distribution": _regime_variance(years),
    }

    best = max(years, key=lambda y: float(y["profit_factor"]))
    worst = min(years, key=lambda y: float(y["profit_factor"]))
    largest_drift = _largest_drift(years, variances)
    largest_trade_drop = _year_over_year_drops(years, key="trades")
    largest_pf_drop = _year_over_year_drops(years, key="profit_factor")

    result = {
        "phase": "14.10",
        "stage": 2,
        "description": "Yearly drift analysis from Stage 1 metrics only",
        "source": str(in_path),
        "symbol": stage1.get("symbol"),
        "timeframe": stage1.get("timeframe"),
        "active_years": len(years),
        "years_analysed": sorted(int(y["year"]) for y in years),
        "variances": variances,
        "best_year": {
            "year": int(best["year"]),
            "profit_factor": best["profit_factor"],
            "expectancy": best["expectancy"],
            "trades": best["trades"],
        },
        "worst_year": {
            "year": int(worst["year"]),
            "profit_factor": worst["profit_factor"],
            "expectancy": worst["expectancy"],
            "trades": worst["trades"],
        },
        "largest_drift": largest_drift,
        "largest_trade_drop": largest_trade_drop,
        "largest_pf_drop": largest_pf_drop,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_path = stage2_output_path(base_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["output_path"] = str(out_path)
    return result
