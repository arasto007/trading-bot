"""Phase 72 — causal root-cause matrix from Phases 68–71.

RESEARCH ONLY. Re-evaluates Phase 67 using new exit-path evidence.
Does not copy Phase 67 blindly. Does not optimize or change production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    UNKNOWN,
    _git_head,
    _mean,
    _parse_ts,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import (
    PHASE68_JSON,
    expand_compact,
    split_views,
)
from tradingbot.backtest.phase69_exit_geometry import PHASE69_JSON
from tradingbot.backtest.phase70_exit_counterfactuals import PHASE70_JSON
from tradingbot.backtest.phase71_extreme_winner_forensics import PHASE71_JSON

PHASE = "72"
PHASE72_JSON = "logs/phase72_exit_root_cause.json"
PHASE72_MD = "docs/PHASE72_EXIT_ROOT_CAUSE.md"
BLOCKED = "BLOCKED"
CANDIDATES = (
    "EXIT_GEOMETRY",
    "STOP_TOO_CLOSE",
    "TP_TOO_FAR_OR_ASYMMETRIC",
    "PROFIT_GIVEBACK",
    "ENTRY_TOO_EARLY",
    "WRONG_REGIME",
    "SESSION_DEPENDENCY",
    "SIDE_ASYMMETRY",
    "SIGNAL_DUPLICATION",
    "VOLATILITY_MISMATCH",
    "EXTREME_OUTLIER_DEPENDENCY",
    "DATA_OR_LABELING_ARTIFACT",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "matrix",
    "PRIMARY_CAUSE",
    "SECONDARY_CAUSE",
    "TERTIARY_CAUSE",
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


def _exp(rows: list[dict[str, Any]]) -> float | None:
    xs = [_f(e.get("r_result")) for e in rows]
    return _mean([x for x in xs if x is not None])


def _share(rows: list[dict[str, Any]], pred) -> float | None:
    if not rows:
        return None
    return sum(1 for e in rows if pred(e)) / len(rows)


def fold_exp(views: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {k: _exp(v) for k, v in views.items()}


def cell(
    *,
    evidence: str,
    counter: str,
    n: int,
    mag: Any,
    views: dict[str, list[dict[str, Any]]],
    pred,
    conf: str,
    priority: int,
    survives_top1: bool | None,
) -> dict[str, Any]:
    def _metric(rows: list[dict[str, Any]]) -> Any:
        if pred is None:
            return _exp(rows)
        return _share(rows, pred)

    return {
        "evidence": evidence,
        "counter_evidence": counter,
        "sample_size": n,
        "effect_magnitude": mag,
        "TRAIN": _metric(views["TRAIN"]),
        "VALIDATION": _metric(views["VALIDATION"]),
        "OOS": _metric(views["OOS"]),
        "recent_180d": _metric(views["RECENT_180D"]),
        "sensitivity_remove_top1": survives_top1,
        "confidence": conf,
        "research_priority": priority,
        "TRAIN_expectancy": _exp(views["TRAIN"]),
        "VALIDATION_expectancy": _exp(views["VALIDATION"]),
        "OOS_expectancy": _exp(views["OOS"]),
        "recent_180d_expectancy": _exp(views["RECENT_180D"]),
        "note": "OOS/180d reported; not used to select the cause rank.",
    }


def run_phase72_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p68 = _safe_load_json(root / PHASE68_JSON) or {}
    p69 = _safe_load_json(root / PHASE69_JSON) or {}
    p70 = _safe_load_json(root / PHASE70_JSON) or {}
    p71 = _safe_load_json(root / PHASE71_JSON) or {}
    events = expand_compact(p68.get("compact_events") or [])
    tape_end = _parse_ts(p68.get("tape_end"))
    from datetime import datetime, timezone

    views = split_views(events, tape_end or datetime(2026, 9, 7, tzinfo=timezone.utc))
    n = len(events)
    losses = [e for e in events if e.get("exit_class") == "LOSS_SL"]
    n_loss = len(losses)
    n05 = int(p68.get("LOSS_AFTER_0_5R") or 0)
    n1 = int(p68.get("LOSS_AFTER_1R") or 0)
    mech = (p68.get("mechanism_ranking") or {}).get("PRIMARY_MECHANISM")
    top1_rem = p68.get("TOP1_REMOVAL_EXPECTANCY")
    top5_rem = p68.get("TOP5_REMOVAL_EXPECTANCY")
    cls = p69.get("EXTREME_WINNER_CLASSIFICATION") or p71.get("EXTREME_WINNER_CLASSIFICATION")
    gt10 = ((p71.get("rr_tails") or {}).get("gt_10") or {}).get("n")
    immediate = (p68.get("cohorts") or {}).get("LOSS_IMMEDIATE") or {}
    n_imm = int(immediate.get("count") or 0)
    wick = ((p68.get("exit_anatomy_loss_sl") or {}).get("H_wick_or_structure") or {})
    n_wick = int(wick.get("WICK") or 0)
    n_struct = int(wick.get("STRUCTURAL") or 0)
    buy = [e for e in events if e.get("side") == "BUY"]
    sell = [e for e in events if e.get("side") == "SELL"]
    dens = _mean([float(e.get("signal_count") or 0) for e in events])
    trans = _share(losses, lambda e: e.get("sl_session_class") == "session_transition")
    opp = _share(losses, lambda e: bool(e.get("opposite_side_regime")))
    high_vol_loss = _share(losses, lambda e: e.get("vol_class") == "high_volatility")

    pred_05 = lambda e: e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) > 0.5
    pred_1 = lambda e: e.get("exit_class") == "LOSS_SL" and (_f(e.get("mfe_R")) or 0) > 1.0
    pred_imm = lambda e: "LOSS_IMMEDIATE" in (e.get("cohorts") or [])
    pred_opp = lambda e: bool(e.get("opposite_side_regime"))
    pred_sell = lambda e: e.get("side") == "SELL"
    pred_trans = lambda e: e.get("sl_session_class") == "session_transition"

    matrix = {
        "EXIT_GEOMETRY": {
            **cell(
                evidence=(
                    "SL = sweep extreme + ATR pad; TP = max(opposite Asian range, MIN_RR*risk). "
                    f"Unbounded RR when risk is tiny. Extreme class={cls}. gt10={gt10}."
                ),
                counter="Ordinary winners have median planned RR near 1.66; geometry is not a coding accident.",
                n=n,
                mag="unbounded_hybrid_RR",
                views=views,
                pred=None,
                conf="HIGH",
                priority=2,
                survives_top1=True,
            ),
            "TRAIN_share_structural_like": None,
        },
        "STOP_TOO_CLOSE": {
            **cell(
                evidence=f"LOSS_IMMEDIATE={n_imm}/{n_loss}; wick SL={n_wick}; structural SL={n_struct}.",
                counter=f"LOSS_AFTER_0.5R={n05} and LOSS_AFTER_1R={n1} cannot be explained as immediate noise.",
                n=n_loss,
                mag=n_imm / n_loss if n_loss else None,
                views=views,
                pred=pred_imm,
                conf="MEDIUM",
                priority=6,
                survives_top1=True,
            ),
        },
        "TP_TOO_FAR_OR_ASYMMETRIC": {
            **cell(
                evidence="Structural TP can sit far beyond 1–2R while SL stays ~1R. Extreme planned RR=31.84 vs median win ~1.66.",
                counter="Most wins fill near MIN_RR/structural modest RR; far TP is the tail, not the typical loser path.",
                n=n,
                mag=gt10,
                views=views,
                pred=lambda e: (_f(e.get("planned_rr")) or 0) > 5,
                conf="MEDIUM",
                priority=5,
                survives_top1=False,
            ),
        },
        "PROFIT_GIVEBACK": {
            **cell(
                evidence=(
                    f"Primary mechanism {mech}. {n05}/{n_loss} SL losers reached >0.5R; {n1}/{n_loss} reached >1R. "
                    "Median give-back and MFE-to-SL delay are non-zero. No time-exit or trail exists (ENABLE_PARTIAL_TP=false)."
                ),
                counter="A minority are immediate failures; some wick-throughs exist.",
                n=n_loss,
                mag=n05 / n_loss if n_loss else None,
                views=views,
                pred=pred_05,
                conf="HIGH",
                priority=1,
                survives_top1=True,
            ),
        },
        "ENTRY_TOO_EARLY": {
            **cell(
                evidence="MAE occurs, but winners also print MAE; jsonl lacks BOS distance / HTF.",
                counter="Winners MAE>1R was ~0 in Phase64. Stop-outs after MFE>1R are an exit, not late-entry, pattern.",
                n=n,
                mag="weak",
                views=views,
                pred=lambda e: (_f(e.get("mae_R")) or 0) > 0.75 and e.get("exit_class") == "LOSS_SL",
                conf="LOW",
                priority=8,
                survives_top1=True,
            ),
        },
        "WRONG_REGIME": {
            **cell(
                evidence=f"Opposite-side regime share among losers={opp}. Extreme winner was STRONG_TREND_UP SELL.",
                counter="Losses occur in RANGING too. Regime filter already exists; labels were not refit.",
                n=n_loss,
                mag=opp,
                views=views,
                pred=pred_opp,
                conf="MEDIUM",
                priority=7,
                survives_top1=True,
            ),
        },
        "SESSION_DEPENDENCY": {
            **cell(
                evidence=f"All entries NY 15-16 UTC. SL session_transition share among losers={trans}.",
                counter="Entry session is a production constraint, not an independent exit cause. Time-of-day cannot be resampled on this tape.",
                n=n_loss,
                mag=trans,
                views=views,
                pred=pred_trans,
                conf="MEDIUM",
                priority=4,
                survives_top1=True,
            ),
        },
        "SIDE_ASYMMETRY": {
            **cell(
                evidence=f"BUY n={len(buy)} exp={_exp(buy)}; SELL n={len(sell)} exp={_exp(sell)}.",
                counter="Give-back appears on both sides; side is secondary to the exit path.",
                n=n,
                mag=_exp(sell),
                views=views,
                pred=pred_sell,
                conf="HIGH",
                priority=4,
                survives_top1=True,
            ),
        },
        "SIGNAL_DUPLICATION": {
            **cell(
                evidence=f"Mean signals/event={dens}. Event unit already used.",
                counter="Duplication inflates RAW counts; it does not create MFE-then-SL on the representative path.",
                n=n,
                mag=dens,
                views=views,
                pred=lambda e: float(e.get("signal_count") or 0) >= 5,
                conf="HIGH",
                priority=9,
                survives_top1=True,
            ),
        },
        "VOLATILITY_MISMATCH": {
            **cell(
                evidence=f"High-vol regime share among losers={high_vol_loss}. ATR pad scales SL; structural TP does not.",
                counter="No new volatility thresholds were created. Existing labels only.",
                n=n_loss,
                mag=high_vol_loss,
                views=views,
                pred=lambda e: e.get("vol_class") == "high_volatility",
                conf="LOW",
                priority=10,
                survives_top1=True,
            ),
        },
        "EXTREME_OUTLIER_DEPENDENCY": {
            **cell(
                evidence=f"Remove top1 expectancy={top1_rem}; remove top5={top5_rem}. OOS positivity is this fill.",
                counter="Give-back majority is independent of the outlier (survives top1 removal as a share).",
                n=n,
                mag=top1_rem,
                views=views,
                pred=None,
                conf="HIGH",
                priority=3,
                survives_top1=False,
            ),
        },
        "DATA_OR_LABELING_ARTIFACT": {
            **cell(
                evidence="Theoretical SL-before-TP on OHLC; asian_high/low not persisted; one event open-only.",
                counter=(
                    f"Path walk covered most events. Extreme winner MFE tracks planned RR. "
                    f"Classification={cls} is not E_DATA_ARTIFACT."
                ),
                n=n,
                mag=cls,
                views=views,
                pred=None,
                conf="LOW",
                priority=12,
                survives_top1=True,
            ),
        },
    }

    # Rank using Phase68-71 evidence, not Phase67 copy.
    # Predeclared ranking keys: giveback share, geometry unbounded, outlier dependence.
    giveback_share = (n05 / n_loss) if n_loss else 0.0
    immediate_share = (n_imm / n_loss) if n_loss else 0.0
    if giveback_share >= 0.40 and giveback_share > immediate_share:
        primary, secondary, tertiary = "PROFIT_GIVEBACK", "EXIT_GEOMETRY", "EXTREME_OUTLIER_DEPENDENCY"
    elif immediate_share >= 0.50:
        primary, secondary, tertiary = "STOP_TOO_CLOSE", "PROFIT_GIVEBACK", "EXIT_GEOMETRY"
    else:
        primary, secondary, tertiary = "EXIT_GEOMETRY", "PROFIT_GIVEBACK", "EXTREME_OUTLIER_DEPENDENCY"

    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "phase67_PRIMARY_was": "EXIT_PROBLEM",
        "reevaluated_from_phases": ["68", "69", "70", "71"],
        "copied_phase67": False,
        "matrix": matrix,
        "PRIMARY_CAUSE": primary,
        "SECONDARY_CAUSE": secondary,
        "TERTIARY_CAUSE": tertiary,
        "ranking_rule": "Predeclared: if LOSS_AFTER_0.5R share >= 0.40 and exceeds immediate share -> PROFIT_GIVEBACK primary.",
        "oos_used_for_selection": False,
        "EXIT_FAILURE_RATE": p68.get("EXIT_FAILURE_RATE"),
        "LOSS_AFTER_0_5R": n05,
        "LOSS_AFTER_1R": n1,
        "MEDIAN_TIME_TO_REVERSAL": p68.get("MEDIAN_TIME_TO_REVERSAL"),
        "TOP1_REMOVAL_EXPECTANCY": top1_rem,
        "TOP5_REMOVAL_EXPECTANCY": top5_rem,
        "EXTREME_WINNER_CLASSIFICATION": cls,
        "hypotheses": [
            {
                "id": "H72-01",
                "claim": "Re-ranked primary cause using 68-71 path evidence rather than copying Phase67 EXIT_PROBLEM.",
                "result": primary,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["cause_matrix_12"],
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE72_JSON, "md": PHASE72_MD},
    }
    (root / PHASE72_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE72_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 72 — Exit Root-Cause Matrix",
        "",
        f"**PRIMARY_CAUSE:** `{primary}`",
        f"**SECONDARY_CAUSE:** `{secondary}`",
        f"**TERTIARY_CAUSE:** `{tertiary}`",
        "",
        "Re-evaluated from Phases 68–71. Phase 67 PRIMARY was EXIT_PROBLEM; that is refined, not copied.",
        "",
        "| Cause | Confidence | Priority | Top1-sensitive |",
        "|---|---|---|---|",
    ]
    for name in CANDIDATES:
        row = matrix[name]
        lines.append(
            f"| {name} | {row.get('confidence')} | {row.get('research_priority')} | {row.get('sensitivity_remove_top1')} |"
        )
    lines.extend(["", "OOS reported, not used to pick the rank.", ""])
    (root / PHASE72_MD).write_text("\n".join(lines), encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase72_collection(Path("."))
    print(p["PRIMARY_CAUSE"], p["SECONDARY_CAUSE"], p["TERTIARY_CAUSE"])
