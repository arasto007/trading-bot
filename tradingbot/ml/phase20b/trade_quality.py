"""Phase 20B — trade quality scoring."""

from __future__ import annotations

from typing import Any

import numpy as np


def _score_entry(t: dict[str, Any]) -> float:
    conf = float(t.get("confidence", 0.5))
    filt = 1.0 if t.get("filter_passed", True) else 0.0
    rsi = float(t.get("rsi", 50))
    adx = float(t.get("adx", 25))
    rsi_mid = 1.0 if 40 <= rsi <= 60 else 0.4
    adx_ok = 1.0 if 15 <= adx <= 50 else 0.4
    return round(0.4 * conf + 0.2 * filt + 0.2 * rsi_mid + 0.2 * adx_ok, 4)


def _score_exit(t: dict[str, Any]) -> float:
    r = float(t.get("r_multiple", t.get("pnl_r", 0)))
    mfe = float(t.get("mfe", max(r, 0)))
    mae = float(t.get("mae", min(r, 0)))
    if mfe <= 0 and r <= 0:
        return 0.2
    capture = r / mfe if mfe > 1e-9 else (1.0 if r > 0 else 0.0)
    adverse = min(1.0, abs(mae) / 2.0) if mae < 0 else 0.0
    return round(max(0.0, min(1.0, 0.7 * max(capture, 0) + 0.3 * (1 - adverse))), 4)


def _score_risk_efficiency(t: dict[str, Any]) -> float:
    r = float(t.get("r_multiple", t.get("pnl_r", 0)))
    risk = float(t.get("risk_percent", 0.005))
    # Higher R per unit risk is better; normalize around 0.5% risk
    return round(max(0.0, min(1.0, (r + 1.0) / 3.0)), 4)


def _score_hold(t: dict[str, Any]) -> float:
    bars = int(t.get("duration_bars", 0))
    r = float(t.get("r_multiple", t.get("pnl_r", 0)))
    if bars <= 0:
        return 0.5
    # Prefer wins that resolve quickly and losses that don't linger
    if r > 0:
        return round(max(0.2, min(1.0, 2.0 / bars)), 4)
    return round(max(0.1, min(1.0, 1.0 / bars)), 4)


def score_trades(observation: dict[str, Any]) -> dict[str, Any]:
    trades = observation.get("trades") or []
    scored = []
    for t in trades:
        if "r_multiple" not in t and "pnl_r" not in t:
            continue
        entry = _score_entry(t)
        exit_s = _score_exit(t)
        risk_e = _score_risk_efficiency(t)
        hold = _score_hold(t)
        conf = float(t.get("confidence", 0.5))
        overall = round(0.25 * entry + 0.25 * exit_s + 0.25 * risk_e + 0.15 * hold + 0.10 * conf, 4)
        scored.append({
            "timestamp": t.get("timestamp"),
            "regime": t.get("regime"),
            "r_multiple": t.get("r_multiple", t.get("pnl_r")),
            "entry_quality": entry,
            "exit_quality": exit_s,
            "risk_efficiency": risk_e,
            "hold_time_efficiency": hold,
            "confidence_consistency": conf,
            "overall_quality": overall,
        })

    if not scored:
        return {"phase": "20B", "trades": 0, "mean_overall_quality": 0.0, "scores": []}

    means = {
        "entry_quality": float(np.mean([s["entry_quality"] for s in scored])),
        "exit_quality": float(np.mean([s["exit_quality"] for s in scored])),
        "risk_efficiency": float(np.mean([s["risk_efficiency"] for s in scored])),
        "hold_time_efficiency": float(np.mean([s["hold_time_efficiency"] for s in scored])),
        "confidence_consistency": float(np.mean([s["confidence_consistency"] for s in scored])),
        "overall_quality": float(np.mean([s["overall_quality"] for s in scored])),
    }
    return {
        "phase": "20B",
        "trades": len(scored),
        "mean_scores": {k: round(v, 4) for k, v in means.items()},
        "mean_overall_quality": round(means["overall_quality"], 4),
        "scores": scored[:200],
    }
