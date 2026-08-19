"""Phase 22I — select best candidate from Dataset A results."""

from __future__ import annotations

from typing import Any


def compare_candidates(results: list[dict[str, Any]], *, baseline_id: str = "22I-BASELINE") -> dict[str, Any]:
    baseline = next((r for r in results if r.get("candidate_id") == baseline_id), results[0] if results else {})
    ranked = sorted(
        results,
        key=lambda r: (
            float(r.get("profit_factor") or 0),
            float(r.get("expectancy") or -999),
            int(r.get("trades") or 0),
        ),
        reverse=True,
    )

    rows = []
    for r in ranked:
        b_pf = float(baseline.get("profit_factor") or 0)
        pf = float(r.get("profit_factor") or 0)
        rows.append({
            "candidate_id": r.get("candidate_id"),
            "title": r.get("title"),
            "trades": r.get("trades"),
            "buy_emitted": r.get("buy_emitted"),
            "sell_emitted": r.get("sell_emitted"),
            "hold_pct": r.get("hold_pct"),
            "profit_factor": pf,
            "expectancy": r.get("expectancy"),
            "max_drawdown_pct": r.get("max_drawdown_pct"),
            "win_rate_pct": r.get("win_rate_pct"),
            "decision_hold": r.get("decision_hold"),
            "pf_delta_vs_baseline": round(pf - b_pf, 4),
            "trades_delta_vs_baseline": (r.get("trades") or 0) - (baseline.get("trades") or 0),
        })

    best = ranked[0] if ranked else {}
    return {
        "phase": "22I",
        "baseline_id": baseline_id,
        "baseline_metrics": {
            "trades": baseline.get("trades"),
            "profit_factor": baseline.get("profit_factor"),
            "expectancy": baseline.get("expectancy"),
            "hold_pct": baseline.get("hold_pct"),
        },
        "ranked": rows,
        "best_candidate_id": best.get("candidate_id"),
    }


def select_recommended(results: list[dict[str, Any]], comparison: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.ml.research.phase22i.candidates import list_policy_candidates
    from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy
    from tradingbot.ml.research.phase22c.config import load_phase22c_config

    cfg22 = load_phase22c_config()
    policy = DecisionPolicy(
        min_confidence=cfg22.decision_min_confidence if cfg22.enabled else DecisionPolicy().min_confidence,
    )
    catalog = {c.id: c for c in list_policy_candidates(policy=policy)}
    baseline = next((r for r in results if r.get("candidate_id") == "22I-BASELINE"), {})

    eligible = [
        r for r in results
        if r.get("candidate_id") != "22I-BASELINE"
        and float(r.get("profit_factor") or 0) >= float(baseline.get("profit_factor") or 0)
    ]
    if not eligible:
        eligible = [r for r in results if r.get("candidate_id") != "22I-BASELINE"]

    pick = max(
        eligible,
        key=lambda r: (
            float(r.get("profit_factor") or 0),
            float(r.get("expectancy") or -999),
            int(r.get("trades") or 0),
        ),
    )
    meta = catalog.get(pick.get("candidate_id", ""))
    b_trades = baseline.get("trades") or 0
    p_trades = pick.get("trades") or 0
    b_hold = baseline.get("hold_pct") or 0
    p_hold = pick.get("hold_pct") or 0

    return {
        "phase": "22I",
        "selected_id": pick.get("candidate_id"),
        "title": pick.get("title"),
        "engineering_type": meta.engineering_type if meta else "unknown",
        "threshold_tuning": meta.threshold_tuning if meta else False,
        "problem": "Decision engine produces HOLD on majority of bars before downstream gates.",
        "proposed_change": meta.description if meta else "",
        "implementation_files": [
            "tradingbot/ml/decision_engine/confidence_engine.py",
            "tradingbot/ml/decision_engine/decision_policy.py",
            "tradingbot/ml/research/phase15i/recovery_adapter.py",
        ],
        "predicted_impact": {
            "profit_factor_improvement": comparison.get("ranked", [{}])[0].get("pf_delta_vs_baseline"),
            "trade_frequency_improvement_pct": round((p_trades - b_trades) / max(b_trades, 1) * 100, 1),
            "hold_pct_change": round((p_hold or 0) - (b_hold or 0), 2),
            "engineering_risk": "LOW" if meta and not meta.threshold_tuning else "MEDIUM",
            "validation_time_dataset_a_min": 20,
        },
        "why_this_candidate": (
            f"Highest PF ({pick.get('profit_factor')}) among simulated policies on Dataset A M5 "
            f"with {pick.get('trades')} trades vs baseline {b_trades}."
        ),
        "do_not_implement_yet": True,
    }
