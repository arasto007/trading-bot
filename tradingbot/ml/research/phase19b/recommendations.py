"""Phase 19B — rank safe improvements (no implementation)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.research.phase19b.config import TARGET_EXPECTANCY, TARGET_MAX_DD, TARGET_PF
from tradingbot.ml.research.phase19b.walkforward import _rebuild_filter, _train_percentile_filter


def _apply_named(name: str, trades: list[dict]) -> list[dict]:
    fn = _rebuild_filter(name)
    if fn is None:
        fn = _train_percentile_filter(name, trades)
    if fn is None:
        return trades
    return [t for t in trades if fn(t)]


def build_recommendations(
    trades: list[dict[str, Any]],
    *,
    filter_report: dict[str, Any],
    exit_report: dict[str, Any],
    sizing_report: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
) -> dict[str, Any]:
    baseline = compute_performance(trades)
    years = max(1, len({t["year"] for t in trades}))
    baseline_tpy = baseline["trades"] / years

    mc_pass = {r["name"] for r in montecarlo.get("passed", [])}
    wf_pass = {r["name"] for r in walkforward.get("survivors", [])}
    safe_names = mc_pass & wf_pass

    ranked = []
    for name in safe_names:
        kept = _apply_named(name, trades)
        perf = compute_performance(kept)
        ranked.append({
            "name": name,
            "type": "filter",
            "profit_factor": perf["profit_factor"],
            "expectancy_r": perf["expectancy_r"],
            "maximum_drawdown_r": perf["maximum_drawdown_r"],
            "win_rate": perf["win_rate"],
            "trades_per_year": round(perf["trades"] / years, 1),
            "expected_impact": {
                "profit_factor": round(perf["profit_factor"] - baseline["profit_factor"], 4),
                "expectancy": round(perf["expectancy_r"] - baseline["expectancy_r"], 4),
                "max_drawdown": round(abs(perf["maximum_drawdown_r"]) - abs(baseline["maximum_drawdown_r"]), 4),
                "win_rate": round(perf["win_rate"] - baseline["win_rate"], 4),
                "trades_per_year": round(perf["trades"] / years - baseline_tpy, 1),
            },
            "meets_targets": (
                perf["profit_factor"] >= TARGET_PF
                and perf["expectancy_r"] >= TARGET_EXPECTANCY
                and abs(perf["maximum_drawdown_r"]) <= TARGET_MAX_DD
            ),
            "implementation_risk": "LOW",
            "walkforward_stable": True,
            "montecarlo_passed": True,
        })

    # Exit / sizing are research-only suggestions with higher risk — include if clearly better
    for v in exit_report.get("variants", [])[:3]:
        if v.get("pf_delta", 0) > 0.05 and v.get("exp_delta", 0) > 0:
            ranked.append({
                "name": f"exit_{v['name']}",
                "type": "exit",
                "profit_factor": v["profit_factor"],
                "expectancy_r": v["expectancy_r"],
                "maximum_drawdown_r": v["maximum_drawdown_r"],
                "win_rate": v["win_rate"],
                "trades_per_year": round(baseline_tpy, 1),
                "expected_impact": {
                    "profit_factor": v["pf_delta"],
                    "expectancy": v["exp_delta"],
                    "max_drawdown": v["dd_delta"],
                    "win_rate": round(v["win_rate"] - baseline["win_rate"], 4),
                    "trades_per_year": 0.0,
                },
                "meets_targets": (
                    v["profit_factor"] >= TARGET_PF
                    and v["expectancy_r"] >= TARGET_EXPECTANCY
                    and abs(v["maximum_drawdown_r"]) <= TARGET_MAX_DD
                ),
                "implementation_risk": "MED",
                "walkforward_stable": False,
                "montecarlo_passed": False,
                "note": "Exit variants require separate live validation — not auto-promoted",
            })

    for v in sizing_report.get("variants", [])[:3]:
        if v.get("name") == "fixed_fractional_0.5pct":
            continue
        if v.get("pf_delta", 0) >= 0 and v.get("dd_delta_pct", 0) < 0:
            ranked.append({
                "name": f"sizing_{v['name']}",
                "type": "position_sizing",
                "profit_factor": v["profit_factor"],
                "expectancy_r": v["expectancy_r"],
                "maximum_drawdown_r": v["maximum_drawdown_r"],
                "win_rate": baseline["win_rate"],
                "trades_per_year": round(baseline_tpy, 1),
                "expected_impact": {
                    "profit_factor": v["pf_delta"],
                    "expectancy": v["exp_delta"],
                    "max_drawdown": v["dd_delta_pct"],
                    "win_rate": 0.0,
                    "trades_per_year": 0.0,
                },
                "meets_targets": False,
                "implementation_risk": v.get("implementation_risk", "MED"),
                "walkforward_stable": False,
                "montecarlo_passed": False,
                "note": "Sizing research only — does not change trade selection",
            })

    # Safe list: filters that passed WF+MC only
    safe = [r for r in ranked if r["type"] == "filter" and r["walkforward_stable"] and r["montecarlo_passed"]]
    safe.sort(key=lambda x: (-x["expected_impact"]["profit_factor"], -x["expected_impact"]["expectancy"]))

    return {
        "phase": "19B",
        "baseline": {
            "profit_factor": baseline["profit_factor"],
            "expectancy_r": baseline["expectancy_r"],
            "maximum_drawdown_r": baseline["maximum_drawdown_r"],
            "win_rate": baseline["win_rate"],
            "trades_per_year": round(baseline_tpy, 1),
        },
        "targets": {
            "profit_factor": TARGET_PF,
            "expectancy_r": TARGET_EXPECTANCY,
            "max_drawdown_r": TARGET_MAX_DD,
        },
        "safe_improvements": safe,
        "all_ranked": ranked,
        "top_improvements": safe[:5],
    }
