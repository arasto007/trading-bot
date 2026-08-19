"""Phase 17A — ranked upgrade roadmap."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17a.config import TOP5_FEATURES


def build_roadmap(
    scores: dict[str, Any],
    compatibility: dict[str, Any],
    risks: dict[str, Any],
) -> dict[str, Any]:
    by_id = {c["id"]: c for c in scores["candidates"]}
    compat_by_id = {r["id"]: r for r in compatibility["rows"]}
    risk_by_id = {r["id"]: r for r in risks["rows"]}

    # Option 1: best balance among viable options (exclude A status-quo-fail, B non-viable).
    viable = [c for c in scores["candidates"] if c["viable"] and c["id"] != "A"]
    best_balance = max(viable, key=lambda c: c["composite_balance"])
    best_perf = max(viable, key=lambda c: c["performance_score"])
    lowest_eng = max(viable, key=lambda c: c["engineering_cost_score"])

    def _option(rank: int, role: str, cand: dict[str, Any]) -> dict[str, Any]:
        cid = cand["id"]
        return {
            "rank": rank,
            "role": role,
            "architecture_id": cid,
            "name": cand["name"],
            "composite_balance": cand["composite_balance"],
            "performance_score": cand["performance_score"],
            "engineering_cost_score": cand["engineering_cost_score"],
            "compatibility_overall": compat_by_id[cid]["overall"],
            "mean_risk": risk_by_id[cid]["mean_risk"],
            "rationale": _rationale(role, cand),
        }

    options = [
        _option(1, "best_balance", best_balance),
        _option(2, "best_performance", best_perf),
        _option(3, "lowest_engineering_cost", lowest_eng),
    ]

    # Deduplicate if same architecture wins multiple roles.
    seen = set()
    unique_options = []
    for opt in options:
        if opt["architecture_id"] in seen:
            # find next-best for that role
            role = opt["role"]
            pool = [c for c in viable if c["id"] not in seen]
            if not pool:
                continue
            if role == "best_performance":
                alt = max(pool, key=lambda c: c["performance_score"])
            elif role == "lowest_engineering_cost":
                alt = max(pool, key=lambda c: c["engineering_cost_score"])
            else:
                alt = max(pool, key=lambda c: c["composite_balance"])
            opt = _option(opt["rank"], role, alt)
        seen.add(opt["architecture_id"])
        unique_options.append(opt)

    return {
        "phase": "17A",
        "options": unique_options,
        "phased_implementation_plan": [
            {
                "step": 1,
                "name": "Feature lab (shadow)",
                "action": f"Compute top-5 candidates offline: {list(TOP5_FEATURES)}",
                "production_change": False,
            },
            {
                "step": 2,
                "name": "Chronological retrain RF",
                "action": "Train new RF on current + top-5; fit scaler on train only; record fingerprint/checksum.",
                "production_change": False,
            },
            {
                "step": 3,
                "name": "Shadow kernel replay",
                "action": "Replay TREND+RANGE; assert RANGE contribution unchanged; TREND throughput improves.",
                "production_change": False,
            },
            {
                "step": 4,
                "name": "Calibration / mapping refresh (research)",
                "action": "Re-fit calibration on new score distribution without changing RiskGate thresholds.",
                "production_change": False,
            },
            {
                "step": 5,
                "name": "Promotion gate",
                "action": "Separate approved phase only; swap trend bundle; keep phase9_9 frozen.",
                "production_change": True,
                "requires_explicit_approval": True,
            },
        ],
        "range_engine_guarantee": "phase9_9 remains frozen and isolated in all roadmap steps",
    }


def _rationale(role: str, cand: dict[str, Any]) -> str:
    if role == "best_balance":
        return (
            f"{cand['name']} balances TREND recovery (features + RF capacity) with "
            "lowest production risk among viable upgrades; preserves sklearn interface."
        )
    if role == "best_performance":
        return (
            f"{cand['name']} maximizes expected probability spread and throughput "
            "per Phase 16D surrogate ceilings; higher ops cost."
        )
    return (
        f"{cand['name']} minimizes engineering surface: same model family, "
        "minor calibration/alignment work, easy rollback to trend_rf_v40."
    )
