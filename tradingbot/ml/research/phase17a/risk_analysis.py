"""Phase 17A — risk analysis per architecture (estimate only)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17a.architecture_matrix import ARCHITECTURES

# Risk scores: 0 = low risk, 1 = high risk.
RISK_TYPES = (
    "overfitting",
    "latency",
    "model_drift",
    "interpretability",
    "deployment_complexity",
    "rollback_complexity",
)


def _risks(arch: dict[str, Any]) -> dict[str, float]:
    family = arch["model_family"]
    features = arch["features"]
    ensemble = arch["ensemble"]
    aid = arch["id"]

    if aid == "A":
        return {
            "overfitting": 0.20,
            "latency": 0.15,
            "model_drift": 0.85,  # already drifted
            "interpretability": 0.15,
            "deployment_complexity": 0.05,
            "rollback_complexity": 0.05,
        }
    if aid == "B":
        return {
            "overfitting": 0.30,
            "latency": 0.20,
            "model_drift": 0.90,
            "interpretability": 0.20,
            "deployment_complexity": 0.80,
            "rollback_complexity": 0.40,
        }

    base = {
        "random_forest": {
            "overfitting": 0.35,
            "latency": 0.20,
            "model_drift": 0.40,
            "interpretability": 0.20,
            "deployment_complexity": 0.25,
            "rollback_complexity": 0.20,
        },
        "sklearn_gbm": {
            "overfitting": 0.45,
            "latency": 0.30,
            "model_drift": 0.40,
            "interpretability": 0.35,
            "deployment_complexity": 0.35,
            "rollback_complexity": 0.30,
        },
        "lightgbm": {
            "overfitting": 0.50,
            "latency": 0.25,
            "model_drift": 0.35,
            "interpretability": 0.50,
            "deployment_complexity": 0.55,
            "rollback_complexity": 0.45,
        },
        "xgboost": {
            "overfitting": 0.50,
            "latency": 0.28,
            "model_drift": 0.35,
            "interpretability": 0.50,
            "deployment_complexity": 0.55,
            "rollback_complexity": 0.45,
        },
        "stack_rf_gbm": {
            "overfitting": 0.60,
            "latency": 0.55,
            "model_drift": 0.45,
            "interpretability": 0.70,
            "deployment_complexity": 0.80,
            "rollback_complexity": 0.70,
        },
        "stack_rf_lgbm": {
            "overfitting": 0.65,
            "latency": 0.60,
            "model_drift": 0.45,
            "interpretability": 0.75,
            "deployment_complexity": 0.85,
            "rollback_complexity": 0.75,
        },
        "stack_rf_xgb": {
            "overfitting": 0.65,
            "latency": 0.60,
            "model_drift": 0.45,
            "interpretability": 0.75,
            "deployment_complexity": 0.85,
            "rollback_complexity": 0.75,
        },
    }.get(family, {r: 0.5 for r in RISK_TYPES})

    risks = dict(base)
    if features == "current_plus_top5":
        risks["overfitting"] = min(1.0, risks["overfitting"] + 0.05)
        risks["deployment_complexity"] = min(1.0, risks["deployment_complexity"] + 0.05)
    if ensemble:
        risks["overfitting"] = min(1.0, risks["overfitting"] + 0.05)

    return {k: round(v, 4) for k, v in risks.items()}


def build_risk_analysis() -> dict[str, Any]:
    rows = []
    for arch in ARCHITECTURES:
        risks = _risks(arch)
        mean_risk = sum(risks.values()) / len(risks)
        rows.append({
            "id": arch["id"],
            "name": arch["name"],
            "risks": risks,
            "mean_risk": round(mean_risk, 4),
            "range_engine_risk": 0.0,  # isolated
            "highest_risk_factor": max(risks, key=risks.get),
        })

    rows_sorted = sorted(rows, key=lambda r: r["mean_risk"])
    return {
        "phase": "17A",
        "risk_types": list(RISK_TYPES),
        "rows": rows,
        "lowest_risk_viable": next(
            (r["id"] for r in rows_sorted if r["id"] not in ("A", "B")),
            "C",
        ),
        "global_constraints": [
            "RANGE engine (phase9_9) must remain frozen and isolated.",
            "RiskGate / DecisionPolicy thresholds unchanged in upgrade path.",
            "Chronological validation mandatory; no shuffle.",
            "Shadow mode before any promotion.",
        ],
    }
