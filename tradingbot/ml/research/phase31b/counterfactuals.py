"""Counterfactual replay transformations for Phase 31B."""

from __future__ import annotations

import copy
from typing import Any

import pandas as pd


def _risk_usd(row: pd.Series) -> float:
    sizing = row.get("sizing")
    if isinstance(sizing, dict):
        return float(sizing.get("dollar_risk_actual") or sizing.get("sl_distance") or 1.0)
    return float(row.get("actual_risk_percent") or 1.0)


def _risk_ratio_configured(row: pd.Series) -> float:
    sizing = row.get("sizing")
    if isinstance(sizing, dict):
        actual = float(sizing.get("dollar_risk_actual") or 1.0)
        configured = float(sizing.get("dollar_risk_configured") or actual)
        return configured / actual if actual > 0 else 1.0
    return 1.0


def baseline_trades(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.to_dict("records")


def replay_a_remove_range(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Replay A — remove only RANGE regime trades.
    Nothing else changes.
    """
    kept = df[df["regime"].astype(str).str.upper() != "RANGE"].copy()
    removed = df[df["regime"].astype(str).str.upper() == "RANGE"]
    notes = {
        "removed_count": int(len(removed)),
        "kept_count": int(len(kept)),
        "all_trades_were_range": len(removed) == len(df),
        "transformation": "exclude regime == RANGE",
    }
    out = kept.to_dict("records")
    for t in out:
        t["counterfactual_pnl"] = t["pnl"]
        t["counterfactual_pnl_r"] = t["pnl_r"]
    return out, notes


def replay_b_perfect_capture(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Replay B — perfect capture efficiency (mathematical only).

    Adds back missed favorable excursion in R-multiples × dollar risk.
    Does NOT change production exit logic — forensic upper bound.
    """
    out_df = df.copy()
    risk = out_df.apply(_risk_usd, axis=1)
    missed = out_df.get("missed_opportunity_r", pd.Series(0, index=out_df.index)).fillna(0)
    mfe_r = out_df.get("mfe_r", pd.Series(0, index=out_df.index)).fillna(0)

    # Primary: recover missed opportunity (capture efficiency fix)
    cf_pnl = out_df["pnl"] + missed * risk

    # Sensitivity: full MFE peak capture upper bound
    cf_pnl_mfe_peak = risk * mfe_r

    out_df["counterfactual_pnl"] = cf_pnl
    out_df["counterfactual_pnl_r"] = out_df["pnl_r"] + missed
    out_df["cf_pnl_mfe_peak"] = cf_pnl_mfe_peak

    notes = {
        "transformation": "pnl + missed_opportunity_r * dollar_risk_actual",
        "trades_improved": int((cf_pnl > out_df["pnl"]).sum()),
        "trades_flipped_to_winner": int(((out_df["pnl"] <= 0) & (cf_pnl > 0)).sum()),
        "mfe_peak_upper_bound_pnl": round(float(cf_pnl_mfe_peak.sum()), 2),
        "production_exits_unchanged": True,
    }
    return out_df.to_dict("records"), notes


def replay_c_remove_min_lot_distortion(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Replay C — remove MIN_LOT_LIMIT dollar distortion.

    Rescale PnL to configured risk exposure (requested lot economics).
    PF invariant under uniform scale; DD and net magnitude change.
    """
    out_df = df.copy()
    ratio = out_df.apply(_risk_ratio_configured, axis=1)
    min_lot = out_df.get("min_lot_limit_applied", pd.Series(True, index=out_df.index))

    cf_pnl = out_df["pnl"] * ratio
    cf_pnl_r = out_df["pnl_r"]  # R-multiples already normalized to actual SL

    out_df["counterfactual_pnl"] = cf_pnl
    out_df["counterfactual_pnl_r"] = cf_pnl_r

    notes = {
        "transformation": "pnl * (dollar_risk_configured / dollar_risk_actual)",
        "avg_scale_ratio": round(float(ratio.mean()), 6),
        "min_lot_trades": int(min_lot.sum()) if hasattr(min_lot, "sum") else len(out_df),
        "pf_invariant_expected": True,
        "distortion_type": "dollar_risk_amplification_not_edge_shape",
    }
    return out_df.to_dict("records"), notes
