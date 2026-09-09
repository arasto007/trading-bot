"""Phase 1.5.60 — PA strategy classification from evidence only."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.pa_live_audit.parity import unexplained_count
from tradingbot.ml.research.pa_live_audit.replay import MIN_TRADES


def classify_phase60(replay: dict[str, Any] | None = None) -> dict[str, Any]:
    """A/B/C/D for the live PA strategy. Does not upgrade on uncosted profit alone."""
    replay = replay or {}
    oos = replay.get("out_of_sample") or {}
    full = replay.get("full") or {}
    n_oos = int(oos.get("trades") or 0)
    n_full = int(full.get("trades") or 0)
    exp_oos = oos.get("expectancy")
    pf_oos = oos.get("profit_factor")
    d_rows = unexplained_count()

    parity_ok = d_rows == 0
    costs_ok = False  # 1.5.51–55: no class-A tape
    identity_ok = False
    live_book_ok = n_oos >= MIN_TRADES and isinstance(exp_oos, (int, float))

    if costs_ok and identity_ok and parity_ok and live_book_ok and (exp_oos or 0) > 0 and (pf_oos or 0) >= 1.2:
        grade = "A"
        label = "demonstrated robust edge + strong live/backtest parity"
    elif live_book_ok and isinstance(exp_oos, (int, float)) and exp_oos > 0 and (pf_oos or 0) >= 1.0:
        grade = "B"
        label = "promising but requires more evidence"
    elif live_book_ok and isinstance(exp_oos, (int, float)) and exp_oos <= 0 and (pf_oos is None or pf_oos < 1.0):
        grade = "D"
        label = "evidence indicates no usable edge"
    else:
        grade = "C"
        label = "insufficient evidence"

    return {
        "classification": grade,
        "label": label,
        "reason": (
            f"uncosted research replay n_full={n_full} n_oos={n_oos} exp_oos={exp_oos} pf_oos={pf_oos}; "
            f"no class-A costs; symbol identity unproven; unexplained parity D-rows={d_rows}. "
            "Profit on uncosted XAUUSD bars is not production proof."
        ),
        "suitable_for_further_validation": grade in ("B", "C") and n_full > 0,
        "suitable_for_paper_shadow": grade == "B",
        "suitable_for_production_activation": False,
        "v41_remains_research_watch_neutral": True,
        "continue_pa_or_return_to_ml": (
            "Keep PA as the live locked path (do not activate ML/v41). "
            "Further PA work is evidence collection (tape/parity), not parameter search. "
            "v41 stays C / 1.0 research-watch."
        ),
        "missing_before_real_money_increase": [
            "XAUUSD_i bid/ask + commission tape",
            "proven XAUUSD vs XAUUSD_i identity",
            "cost-aware replay of this same rule set",
            "live journal of closed PA round-trips n>>30",
            "backtest runner locked to M5 + live preset (no M1 default)",
        ],
    }
