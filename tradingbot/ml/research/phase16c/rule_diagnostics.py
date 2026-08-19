"""Phase 16C — granular TREND rule acceptance / rejection analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_8.trend_variants import ADX_MIN_A, evaluate_variant_a

RULE_GATES = (
    "adx_pass",
    "ema_bullish",
    "ema_bearish",
    "slope_bullish",
    "slope_bearish",
    "hh_structure",
    "ll_structure",
    "buy_signal",
    "sell_signal",
)


def _hh_structure(row: pd.Series) -> bool:
    hh = int(row.get("higher_high_count", 0))
    ll = int(row.get("lower_low_count", 0))
    return hh >= 2 or hh > ll


def _ll_structure(row: pd.Series) -> bool:
    hh = int(row.get("higher_high_count", 0))
    ll = int(row.get("lower_low_count", 0))
    return ll >= 2 or ll > hh


def diagnose_rule_gates(row: pd.Series, *, regime: str = "TREND") -> dict[str, Any]:
    """Per-gate boolean flags and final rule direction."""
    ema20 = float(row.get("ema20", 0))
    ema50 = float(row.get("ema50", 0))
    ema50_slope = float(row.get("ema50_slope", 0))
    adx = float(row.get("adx", 0))

    gates = {
        "adx_pass": adx > ADX_MIN_A,
        "ema_bullish": ema20 > ema50,
        "ema_bearish": ema20 < ema50,
        "slope_bullish": ema50_slope > 0,
        "slope_bearish": ema50_slope < 0,
        "hh_structure": _hh_structure(row),
        "ll_structure": _ll_structure(row),
    }
    buy_ok = (
        gates["adx_pass"]
        and gates["ema_bullish"]
        and gates["slope_bullish"]
        and gates["hh_structure"]
    )
    sell_ok = (
        gates["adx_pass"]
        and gates["ema_bearish"]
        and gates["slope_bearish"]
        and gates["ll_structure"]
    )
    gates["buy_signal"] = buy_ok
    gates["sell_signal"] = sell_ok

    direction = evaluate_variant_a(row, regime=regime)
    rejection = None
    if direction == "HOLD":
        if not gates["adx_pass"]:
            rejection = "adx_below_min"
        elif not buy_ok and not sell_ok:
            if gates["ema_bullish"] and not gates["slope_bullish"]:
                rejection = "bull_slope_fail"
            elif gates["ema_bearish"] and not gates["slope_bearish"]:
                rejection = "bear_slope_fail"
            elif gates["ema_bullish"] and not gates["hh_structure"]:
                rejection = "bull_structure_fail"
            elif gates["ema_bearish"] and not gates["ll_structure"]:
                rejection = "bear_structure_fail"
            elif not gates["ema_bullish"] and not gates["ema_bearish"]:
                rejection = "ema_flat"
            else:
                rejection = "mixed_conditions"
        else:
            rejection = "unknown_hold"

    return {
        "direction": direction,
        "rejection_reason": rejection,
        "gates": gates,
        "adx": adx,
    }


def aggregate_rule_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize rule acceptance, rejection reasons, gate overlap."""
    n = len(records) or 1
    rule_pass = sum(1 for r in records if r.get("rule_direction") in ("BUY", "SELL"))
    rejection_counts: dict[str, int] = {}
    gate_counts: dict[str, int] = {g: 0 for g in RULE_GATES}
    buy_only = sell_only = both = 0

    for r in records:
        diag = r.get("rule_diag", {})
        gates = diag.get("gates", {})
        for g in RULE_GATES:
            if gates.get(g):
                gate_counts[g] += 1
        reason = diag.get("rejection_reason")
        if reason:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        if gates.get("buy_signal") and gates.get("sell_signal"):
            both += 1
        elif gates.get("buy_signal"):
            buy_only += 1
        elif gates.get("sell_signal"):
            sell_only += 1

    top_rejection = sorted(rejection_counts.items(), key=lambda x: -x[1])[:5]
    gate_rates = {g: round(gate_counts[g] / n, 4) for g in RULE_GATES}

    # Redundancy: gates that rarely add marginal acceptance
    marginal = {}
    if gate_counts["adx_pass"] > 0:
        marginal["hh_given_bull_ema"] = round(
            gate_counts["hh_structure"] / max(gate_counts["ema_bullish"], 1), 4,
        )
        marginal["ll_given_bear_ema"] = round(
            gate_counts["ll_structure"] / max(gate_counts["ema_bearish"], 1), 4,
        )

    return {
        "trend_bars": len(records),
        "rule_pass": rule_pass,
        "rule_reject": len(records) - rule_pass,
        "rule_acceptance_rate": round(rule_pass / n, 6),
        "rule_rejection_rate": round((len(records) - rule_pass) / n, 6),
        "rejection_reasons": rejection_counts,
        "top_rejection_reasons": [{"reason": k, "count": v} for k, v in top_rejection],
        "gate_pass_counts": gate_counts,
        "gate_pass_rates": gate_rates,
        "signal_overlap": {"buy_only": buy_only, "sell_only": sell_only, "both": both},
        "marginal_gate_rates": marginal,
        "rules_restrictive_before_rf": (len(records) - rule_pass) / n > 0.5,
    }
