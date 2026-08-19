"""Phase 17A — candidate scoring (estimates only, no model training)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17a.architecture_matrix import ARCHITECTURES
from tradingbot.ml.research.phase17a.config import EVIDENCE

# Score dimensions: higher is better for all except risk/cost/complexity (inverted in composite).
DIMENSIONS = (
    "probability_spread",
    "trend_throughput",
    "pf_stability",
    "latency",
    "explainability",
    "maintenance_cost",
    "production_risk",
    "retraining_complexity",
)


def _base_from_evidence() -> dict[str, float]:
    """Map Phase 16D surrogate evidence into 0–1 estimate scales."""
    frozen_max = EVIDENCE["phase16d_frozen_max_p"]
    exist_max = EVIDENCE["phase16d_surrogate_existing_max_p"]
    comb_max = EVIDENCE["phase16d_surrogate_combined_max_p"]
    return {
        "frozen_spread": 0.15,  # std ~0.013, flat
        "exist_spread": min(1.0, (exist_max - frozen_max) / 0.5),
        "comb_spread": min(1.0, (comb_max - frozen_max) / 0.5),
        "frozen_throughput": 0.05,  # 1 actionable
        "exist_throughput": 0.55,
        "comb_throughput": 0.70,
    }


def _score_architecture(arch: dict[str, Any], base: dict[str, float]) -> dict[str, Any]:
    aid = arch["id"]
    family = arch["model_family"]
    features = arch["features"]
    ensemble = arch["ensemble"]
    retrain = arch["retrain"]
    viable = arch.get("viable", True)

    # Probability spread & throughput from feature set + model capacity.
    if aid == "A":
        spread, throughput, pf = 0.15, 0.05, 0.40
    elif aid == "B":
        # Non-viable: frozen cannot use new features.
        spread, throughput, pf = 0.15, 0.05, 0.40
    elif aid == "C":
        spread = base["comb_spread"] * 0.85  # RF capacity partial
        throughput = base["comb_throughput"] * 0.80
        pf = 0.72
    elif aid == "D":
        spread = base["exist_spread"] * 1.05
        throughput = base["exist_throughput"] * 1.05
        pf = 0.68
    elif aid == "E":
        spread = base["comb_spread"] * 0.95
        throughput = base["comb_throughput"] * 0.92
        pf = 0.75
    elif aid == "F":
        spread = base["exist_spread"] * 1.15
        throughput = base["exist_throughput"] * 1.10
        pf = 0.70
    elif aid == "G":
        spread = min(1.0, base["comb_spread"] * 1.05)
        throughput = min(1.0, base["comb_throughput"] * 1.05)
        pf = 0.78
    elif aid == "H":
        spread = base["exist_spread"] * 1.12
        throughput = base["exist_throughput"] * 1.08
        pf = 0.69
    elif aid == "I":
        spread = min(1.0, base["comb_spread"] * 1.04)
        throughput = min(1.0, base["comb_throughput"] * 1.04)
        pf = 0.77
    elif aid in ("J", "K", "L"):
        spread = min(1.0, base["comb_spread"] * 1.08)
        throughput = min(1.0, base["comb_throughput"] * 1.08)
        pf = 0.80
    else:
        spread, throughput, pf = 0.5, 0.5, 0.5

    # Latency: higher score = faster / lower latency.
    latency_map = {
        "random_forest": 0.85,
        "sklearn_gbm": 0.70,
        "lightgbm": 0.80,
        "xgboost": 0.75,
        "stack_rf_gbm": 0.45,
        "stack_rf_lgbm": 0.40,
        "stack_rf_xgb": 0.40,
    }
    latency = latency_map.get(family, 0.5)

    # Explainability: RF best, stacks worst.
    explain_map = {
        "random_forest": 0.90,
        "sklearn_gbm": 0.70,
        "lightgbm": 0.55,
        "xgboost": 0.55,
        "stack_rf_gbm": 0.35,
        "stack_rf_lgbm": 0.30,
        "stack_rf_xgb": 0.30,
    }
    explainability = explain_map.get(family, 0.5)
    if features == "current_plus_top5" and family == "random_forest":
        explainability = 0.85  # still RF, slightly more features

    # Maintenance cost: higher score = lower cost.
    if aid == "A":
        maintenance = 0.95
    elif aid == "B":
        maintenance = 0.90
    elif family == "random_forest":
        maintenance = 0.80
    elif family == "sklearn_gbm":
        maintenance = 0.70
    elif family in ("lightgbm", "xgboost"):
        maintenance = 0.55
    else:
        maintenance = 0.35

    # Production risk: higher score = lower risk.
    if aid == "A":
        risk = 0.95  # known-bad but zero change risk
    elif aid == "B":
        risk = 0.20  # non-viable / silent failure risk
    elif family == "random_forest" and retrain:
        risk = 0.75  # same interface, new bundle
    elif family == "sklearn_gbm":
        risk = 0.60
    elif family in ("lightgbm", "xgboost"):
        risk = 0.45
    else:
        risk = 0.30

    # Retraining complexity: higher score = simpler.
    if not retrain:
        complexity = 0.95 if aid == "A" else 0.10
    elif family == "random_forest":
        complexity = 0.80
    elif family == "sklearn_gbm":
        complexity = 0.70
    elif family in ("lightgbm", "xgboost"):
        complexity = 0.50
    else:
        complexity = 0.25

    if not viable:
        # Penalize non-viable options heavily on throughput/spread.
        spread = min(spread, 0.15)
        throughput = min(throughput, 0.05)
        pf = min(pf, 0.40)

    scores = {
        "probability_spread": round(spread, 4),
        "trend_throughput": round(throughput, 4),
        "pf_stability": round(pf, 4),
        "latency": round(latency, 4),
        "explainability": round(explainability, 4),
        "maintenance_cost": round(maintenance, 4),
        "production_risk": round(risk, 4),
        "retraining_complexity": round(complexity, 4),
    }

    # Composite: balance performance vs safety (smallest safe upgrade prioritizes risk + maintenance).
    weights = {
        "probability_spread": 0.14,
        "trend_throughput": 0.16,
        "pf_stability": 0.12,
        "latency": 0.08,
        "explainability": 0.10,
        "maintenance_cost": 0.12,
        "production_risk": 0.16,
        "retraining_complexity": 0.12,
    }
    composite = sum(scores[k] * weights[k] for k in weights)
    # Performance-only subscore for roadmap option 2.
    perf = (
        scores["probability_spread"] * 0.35
        + scores["trend_throughput"] * 0.40
        + scores["pf_stability"] * 0.25
    )
    # Engineering-cost subscore (higher = cheaper).
    eng = (
        scores["maintenance_cost"] * 0.30
        + scores["production_risk"] * 0.30
        + scores["retraining_complexity"] * 0.25
        + scores["latency"] * 0.15
    )

    return {
        "id": aid,
        "name": arch["name"],
        "model_family": family,
        "features": features,
        "viable": viable,
        "scores": scores,
        "composite_balance": round(composite, 4),
        "performance_score": round(perf, 4),
        "engineering_cost_score": round(eng, 4),
        "evidence_basis": [
            "phase16d_surrogate_ceilings",
            "phase16c_rf_bottleneck",
            "phase16b_range_isolation",
        ],
    }


def score_all_candidates() -> dict[str, Any]:
    base = _base_from_evidence()
    candidates = [_score_architecture(a, base) for a in ARCHITECTURES]
    candidates_sorted = sorted(candidates, key=lambda c: -c["composite_balance"])
    return {
        "phase": "17A",
        "dimensions": list(DIMENSIONS),
        "candidates": candidates,
        "ranked_by_balance": [c["id"] for c in candidates_sorted],
        "best_balance_id": candidates_sorted[0]["id"],
        "best_performance_id": max(candidates, key=lambda c: c["performance_score"])["id"],
        "lowest_engineering_cost_id": max(
            [c for c in candidates if c["id"] != "A"],
            key=lambda c: c["engineering_cost_score"],
        )["id"],
    }
