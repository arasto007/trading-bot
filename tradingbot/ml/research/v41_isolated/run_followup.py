"""Phase 1.5.46–1.5.50 orchestrator — offline follow-up, does not rewrite prior JSON."""

from __future__ import annotations

import json
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.research.v41_isolated.cost_inventory import run_inventory
from tradingbot.ml.research.v41_isolated.cost_robustness import (
    ROLLING_WINDOWS,
    XAU_PIP_SIZE,
    _slice_table,
    break_even_cost_r,
    classify_phase50,
    concentration,
    duration_bucket,
    extended_sensitivity,
    load_isolated_book,
    oos_trades,
    probability_bucket,
    rolling_trade_windows,
    session_label,
)
from tradingbot.ml.research.v41_isolated.replay import summarize_r


def _stability_verdict(robustness: dict[str, Any], sensitivity: dict[str, Any]) -> str:
    year = robustness.get("year") or []
    sess = robustness.get("session") or []
    neg_sessions = [r for r in sess if not r.get("expectancy_positive")]
    roll = robustness.get("rolling") or {}
    frac = ((roll.get("250") or {}).get("expectancy") or {}).get("frac_positive")
    med = sensitivity.get("0.03R") or {}
    high = sensitivity.get("0.04R") or {}
    if high.get("expectancy_positive") is False:
        return "concentrated_and_disappears_under_modest_costs"
    if neg_sessions and frac is not None and frac < 0.7:
        return "session_dependent_and_unstable_in_rolling_windows"
    if not med.get("expectancy_positive"):
        return "disappearing_under_modest_costs"
    return "thin_and_not_broadly_stable"


def run_phase46_50(*, write_reports: bool = True) -> dict[str, Any]:
    inventory = run_inventory()
    trades = load_isolated_book()
    oos = oos_trades(trades)
    oos_r = [float(t["r_multiple"]) for t in oos]
    oos_2025 = [float(t["r_multiple"]) for t in oos if str(t["timestamp"]).startswith("2025")]
    oos_2026 = [float(t["r_multiple"]) for t in oos if str(t["timestamp"]).startswith("2026")]

    sensitivity = extended_sensitivity(oos_r)
    be = {
        "oos_aggregate": break_even_cost_r(oos_r),
        "oos_2025": break_even_cost_r(oos_2025),
        "oos_2026": break_even_cost_r(oos_2026),
    }
    rolling = {str(w): rolling_trade_windows(oos_r, window=w) for w in ROLLING_WINDOWS}
    robustness = {
        "year": _slice_table(oos, lambda t: str(t["timestamp"])[:4]),
        "month": _slice_table(oos, lambda t: str(t["timestamp"])[:7]),
        "direction": _slice_table(oos, lambda t: str(t.get("direction"))),
        "session": _slice_table(oos, lambda t: session_label(t["timestamp"])),
        "duration": _slice_table(oos, lambda t: duration_bucket(int(t.get("hold_bars") or 0))),
        "probability": _slice_table(oos, lambda t: probability_bucket(float(t.get("probability") or 0))),
        "concentration": concentration(oos),
        "longest_losing_streak": concentration(oos).get("longest_losing_streak"),
        "rolling": rolling,
        "no_filters_applied": True,
    }
    robustness["stability_verdict"] = _stability_verdict(robustness, sensitivity)

    live = ((inventory.get("trade_journal") or {}).get("executions") or {}).get("live_fills") or {}
    live_n = int(live.get("n") or 0)
    payload: dict[str, Any] = {
        "phase": "1.5.46-1.5.50",
        "offline_only": True,
        "prior_json_not_rewritten": [
            "data/ml/reports/phase15_36/v41_isolated_trend_replay.json",
            "data/ml/reports/phase15_41/v41_cost_robustness.json",
        ],
        "pip_size_xau": XAU_PIP_SIZE,
        "inventory": inventory,
        "measured_live_entry_slippage": {
            "n": live_n,
            "sufficient_for_v41_cost_model": live_n >= 30,
            "round_trip": False,
            "engine_of_isolated_book": "trend_rf_v41",
            "journal_symbol": "XAUUSD",
            "live_primary_symbol": "XAUUSD_i",
            "note": (
                "17 live journal fills are real entry-slippage observations, not a spread tape, "
                "not round-trip, not v41-TREND-only, and too small to model 3,409 OOS trades. "
                "No distribution was fabricated from them."
            ),
        },
        "uncosted_oos": summarize_r(oos_r),
        "extended_sensitivity_oos": sensitivity,
        "break_even": be,
        "robustness": robustness,
        "cost_model_audit": {
            "historical_spread_tick_files": int((inventory.get("raw_stores") or {}).get("spread_files") or 0)
            + int((inventory.get("raw_stores") or {}).get("tick_files") or 0),
        },
        "sensitivity_oos": {
            "zero": sensitivity.get("0.00R"),
            "low": sensitivity.get("0.01R"),
            "medium": sensitivity.get("0.03R"),
        },
        "labeled_assumption_scenarios": {},
    }
    payload["decision"] = classify_phase50(payload)

    if write_reports:
        out = reports_dir() / "phase15_46"
        out.mkdir(parents=True, exist_ok=True)
        # Drop bulky live row dump from the written report's nested inventory copy? Keep it — n=17 is tiny.
        (out / "v41_cost_followup.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        payload["report_path"] = str(out / "v41_cost_followup.json")
    return payload


if __name__ == "__main__":
    result = run_phase46_50()
    keep = {
        "decision": result.get("decision"),
        "measured_live_entry_slippage": result.get("measured_live_entry_slippage"),
        "raw_stores": (result.get("inventory") or {}).get("raw_stores"),
        "journal_counts": ((result.get("inventory") or {}).get("trade_journal") or {}).get("counts"),
        "exec_modes": (((result.get("inventory") or {}).get("trade_journal") or {}).get("executions") or {}).get("modes"),
        "extended_sensitivity_oos": result.get("extended_sensitivity_oos"),
        "break_even": result.get("break_even"),
        "rolling": (result.get("robustness") or {}).get("rolling"),
        "stability_verdict": (result.get("robustness") or {}).get("stability_verdict"),
        "year": (result.get("robustness") or {}).get("year"),
        "session": (result.get("robustness") or {}).get("session"),
        "report_path": result.get("report_path"),
    }
    print(json.dumps(keep, indent=2, default=str))
