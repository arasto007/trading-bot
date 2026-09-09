"""Phase 70 — predeclared exit counterfactual diagnostics.

RESEARCH ONLY. No parameter search, no new strategy, no SL/TP moves.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_BOOTSTRAP_SEED,
    PHASE40_JSON,
    PHASE45_JSON,
    UNKNOWN,
    _git_head,
    _mean,
    _median,
    _parse_ts,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import (
    PHASE68_JSON,
    TAPE_END_FALLBACK,
    expand_compact,
    fold_of,
    split_views,
)

PHASE = "70"
PHASE70_JSON = "logs/phase70_exit_counterfactuals.json"
PHASE70_MD = "docs/PHASE70_EXIT_COUNTERFACTUALS.md"
BLOCKED = "BLOCKED"
N_BOOT = 2000
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "diagnostics",
    "oos_used_for_selection",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _f(v: Any) -> float | None:
    try:
        if v is None or v == UNKNOWN:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _ci_mean(xs: list[float], seed: int = PHASE40_BOOTSTRAP_SEED) -> dict[str, Any]:
    if not xs:
        return {"n": 0, "mean": None, "ci95": [None, None]}
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(N_BOOT):
        s = 0.0
        for _i in range(n):
            s += xs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * N_BOOT)]
    hi = means[min(N_BOOT - 1, int(0.975 * N_BOOT))]
    return {"n": n, "mean": _mean(xs), "ci95": [lo, hi], "kind": "DERIVED_BOOTSTRAP", "seed": seed}


def _ci_prop(k: int, n: int, seed: int = PHASE40_BOOTSTRAP_SEED) -> dict[str, Any]:
    if n <= 0:
        return {"n": 0, "p": None, "ci95": [None, None]}
    flags = [1.0] * k + [0.0] * (n - k)
    row = _ci_mean(flags, seed)
    return {"n": n, "count": k, "p": k / n, "ci95": row["ci95"], "kind": "DERIVED_BOOTSTRAP"}


def _effect(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def slice_report(events: list[dict[str, Any]], pred, label: str) -> dict[str, Any]:
    hit = [e for e in events if pred(e)]
    miss = [e for e in events if not pred(e)]
    xs_h = [_f(e.get("r_result")) for e in hit]
    xs_m = [_f(e.get("r_result")) for e in miss]
    xs_h = [x for x in xs_h if x is not None]
    xs_m = [x for x in xs_m if x is not None]
    return {
        "label": label,
        "sample_count": len(hit),
        "complement_count": len(miss),
        "hit": pack_stats(xs_h),
        "complement": pack_stats(xs_m),
        "effect_size_expectancy": _effect(_mean(xs_h), _mean(xs_m)),
        "hit_mean_ci": _ci_mean(xs_h),
        "kind": "COUNTERFACTUAL_DESCRIPTIVE" if "capture" in label.lower() or "window" in label.lower() else "OBSERVED",
    }


def views_block(views: dict[str, list[dict[str, Any]]], pred, label: str) -> dict[str, Any]:
    out = {}
    for name, rows in views.items():
        out[name] = slice_report(rows, pred, label)
    full = out["FULL"]
    wo = out["WITHOUT_TOP1"]
    return {
        "label": label,
        "sample_count": full["sample_count"],
        "effect_size": full["effect_size_expectancy"],
        "confidence_interval": full["hit_mean_ci"]["ci95"],
        "survives_removal_of_top1": bool((wo.get("hit") or {}).get("expectancy_R") is not None),
        "survives_top1_sign": (
            None
            if (wo.get("hit") or {}).get("expectancy_R") is None
            else bool(((wo.get("hit") or {}).get("expectancy_R") or 0) > 0)
            == bool(((full.get("hit") or {}).get("expectancy_R") or 0) > 0)
        ),
        "TRAIN": out["TRAIN"],
        "VALIDATION": out["VALIDATION"],
        "OOS": out["OOS"],
        "RECENT_180D": out["RECENT_180D"],
        "WITHOUT_TOP1": out["WITHOUT_TOP1"],
        "FULL": full,
        "oos_used_for_selection": False,
        "recent_180d_used_for_tuning": False,
    }


def hold_quantile(events: list[dict[str, Any]], q: float) -> float | None:
    xs = sorted(_f(e.get("duration_minutes")) for e in events)
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int((len(xs) - 1) * q)))
    return float(xs[i])


def run_phase70_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p68 = _safe_load_json(root / PHASE68_JSON) or {}
    events = expand_compact(p68.get("compact_events") or [])
    tape_end = _parse_ts(p68.get("tape_end")) or _parse_ts(
        ((p45.get("oos") or {}).get("splits") or {}).get("OOS", {}).get("end_ts")
    ) or datetime(2026, 9, 7, tzinfo=timezone.utc)
    views = split_views(events, tape_end)
    losses = [e for e in events if e.get("exit_class") == "LOSS_SL"]
    n_loss = len(losses)
    n05 = sum(1 for e in losses if "LOSS_AFTER_0.5R" in (e.get("cohorts") or []) or (_f(e.get("mfe_R")) or 0) > 0.5)
    n1 = sum(1 for e in losses if "LOSS_AFTER_1R" in (e.get("cohorts") or []) or (_f(e.get("mfe_R")) or 0) > 1.0)

    def mfe_ge(th: float):
        return lambda e: (_f(e.get("mfe_R")) or 0) >= th and e.get("exit_class") == "LOSS_SL"

    q1 = hold_quantile(events, 0.25)
    q2 = hold_quantile(events, 0.50)
    q3 = hold_quantile(events, 0.75)

    diagnostics = {
        "A_NO_PROFIT_PROTECTION": {
            "kind": "OBSERVED_DESCRIPTIVE",
            "note": "Classify whether eventual SL losers first reached +0.5R / +1R. Not a simulated trail.",
            "LOSS_SL": n_loss,
            "reached_0.5R_before_SL": _ci_prop(n05, n_loss),
            "reached_1R_before_SL": _ci_prop(n1, n_loss),
            **views_block(views, lambda e: e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) > 0.5, "loss_after_0.5R"),
        },
        "B_BREAKEVEN_REACH": {
            "kind": "COUNTERFACTUAL_DESCRIPTIVE",
            "note": "Percentage of eventual SL losers that first reached >= +1R. SL was NOT moved.",
            "pct_sl_losers_reached_1R": _ci_prop(n1, n_loss),
            "sl_actually_moved": False,
            **views_block(views, mfe_ge(1.0), "sl_losers_reached_1R"),
        },
        "C_MFE_CAPTURE": {
            "kind": "COUNTERFACTUAL_DESCRIPTIVE",
            "note": "actual_R / MFE_R. Not a new strategy.",
            "LOSS_SL": pack_stats([_f(e.get("capture_ratio")) for e in losses if _f(e.get("capture_ratio")) is not None]),
            "WIN_TP": pack_stats(
                [
                    _f(e.get("capture_ratio"))
                    for e in events
                    if e.get("exit_class") == "WIN_TP" and _f(e.get("capture_ratio")) is not None
                ]
            ),
            "ALL": pack_stats([_f(e.get("capture_ratio")) for e in events if _f(e.get("capture_ratio")) is not None]),
            **views_block(views, lambda e: (_f(e.get("capture_ratio")) or 0) < 0, "negative_capture"),
        },
        "D_TIME_TO_REVERSAL": {
            "kind": "OBSERVED",
            "median_minutes_mfe_to_sl": _median(
                [_f(e.get("mins_mfe_to_exit")) for e in losses if _f(e.get("mins_mfe_to_exit")) is not None]
            ),
            "mean_minutes_mfe_to_sl": _mean(
                [_f(e.get("mins_mfe_to_exit")) for e in losses if _f(e.get("mins_mfe_to_exit")) is not None]
            ),
            "ci_mean": _ci_mean([_f(e.get("mins_mfe_to_exit")) for e in losses if _f(e.get("mins_mfe_to_exit")) is not None]),
            **views_block(
                views,
                lambda e: e.get("exit_class") == "LOSS_SL" and (_f(e.get("mins_mfe_to_exit")) or 0) > 30,
                "slow_reversal_losses",
            ),
        },
        "E_EXIT_WINDOW": {
            "kind": "OBSERVED",
            "predeclared_quantiles": {"q25": q1, "q50": q2, "q75": q3},
            "note": "Holding-time quartiles predeclared from FULL tape order statistics; not searched.",
            "Q1_hold": views_block(views, lambda e: (_f(e.get("duration_minutes")) or 0) <= (q1 or 0), "hold_q1"),
            "Q4_hold": views_block(views, lambda e: (_f(e.get("duration_minutes")) or 0) > (q3 or 0), "hold_q4"),
        },
        "F_REGIME_EXIT": {
            "kind": "OBSERVED",
            "by_regime": {
                reg: views_block(views, lambda e, r=reg: str(e.get("regime")) == r, f"regime_{reg}")
                for reg in sorted({str(e.get("regime") or UNKNOWN) for e in events})
            },
        },
        "G_SESSION_EXIT": {
            "kind": "OBSERVED",
            "note": "Entries are NY 15-16 UTC by design. Session class is EXIT hour vs entry window.",
            "same_session_sl": views_block(views, lambda e: e.get("sl_session_class") == "same_session" and e.get("exit_class") == "LOSS_SL", "sl_same_session"),
            "transition_sl": views_block(views, lambda e: e.get("sl_session_class") == "session_transition" and e.get("exit_class") == "LOSS_SL", "sl_transition"),
        },
        "H_SIDE_EXIT": {
            "kind": "OBSERVED",
            "BUY": views_block(views, lambda e: e.get("side") == "BUY", "BUY"),
            "SELL": views_block(views, lambda e: e.get("side") == "SELL", "SELL"),
            "BUY_loss_after_0.5R": views_block(
                views,
                lambda e: e.get("side") == "BUY" and e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) > 0.5,
                "BUY_loss_0.5",
            ),
            "SELL_loss_after_0.5R": views_block(
                views,
                lambda e: e.get("side") == "SELL" and e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) > 0.5,
                "SELL_loss_0.5",
            ),
        },
        "I_VOLATILITY_EXIT": {
            "kind": "OBSERVED",
            "note": "Uses existing regime labels only. No new ATR thresholds.",
            "high_volatility": views_block(views, lambda e: e.get("vol_class") == "high_volatility", "high_vol"),
            "low_volatility": views_block(views, lambda e: e.get("vol_class") == "low_volatility", "low_vol"),
        },
    }
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "grid_search": False,
        "random_search": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "diagnostics": diagnostics,
        "LOSS_AFTER_0_5R": n05,
        "LOSS_AFTER_1R": n1,
        "MEDIAN_TIME_TO_REVERSAL": (diagnostics["D_TIME_TO_REVERSAL"].get("median_minutes_mfe_to_sl")),
        "oos_used_for_selection": False,
        "recent_180d_used_for_tuning": False,
        "hypotheses": [
            {"id": "H70-A", "claim": "A large share of SL losers first reached +0.5R.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-B", "claim": "Share of SL losers that reached +1R (breakeven-reach diagnostic; SL not moved).", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-C", "claim": "Capture ratio actual_R/MFE_R is negative for most losers.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-D", "claim": "Time-to-reversal after MFE is measurable and not instantaneous for the majority.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-E", "claim": "Give-back is not confined to a single holding-time quartile.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-F", "claim": "Exit failure varies by existing regime labels.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-G", "claim": "Some SL hits occur after the NY entry window.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-H", "claim": "BUY vs SELL differ in give-back rates.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
            {"id": "H70-I", "claim": "Existing VOLATILE/CRISIS vs RANGING labels differ in exit failure.", "result": "DESCRIPTIVE", "oos_used_for_decision": False},
        ],
        "tests_performed": 9,
        "diagnostics_run": list(diagnostics.keys()),
        "stopped_after_predeclared_set": True,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "SL_TP": "NOT_CHANGED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE70_JSON, "md": PHASE70_MD},
    }
    (root / PHASE70_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE70_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE70_MD).write_text(
        "\n".join(
            [
                "# Phase 70 — Exit Counterfactual Diagnostics",
                "",
                "Predeclared families A–I only. No grid/random search. SL was not moved.",
                f"LOSS_AFTER_0.5R={n05}  LOSS_AFTER_1R={n1} of LOSS_SL={n_loss}.",
                f"MEDIAN_TIME_TO_REVERSAL={payload['MEDIAN_TIME_TO_REVERSAL']}",
                "",
                "OOS and recent 180d are reported, not used for selection or tuning.",
                "COUNTERFACTUAL numbers are not claims the live strategy trailed or moved stops.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase70_collection(Path("."))
    print(p["LOSS_AFTER_0_5R"], p["LOSS_AFTER_1R"])
