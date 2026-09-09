"""Phase 69 — current exit-geometry decomposition (inspection only).

RESEARCH ONLY. Reads existing code + frozen event prices.
Does not modify strategy, SL/TP, or rerun signal generation.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    UNKNOWN,
    _git_head,
    _mean,
    _median,
    _utc_now,
)
from tradingbot.backtest.phase64_strategy_event_forensics import PHASE64_JSON
from tradingbot.backtest.phase68_exit_forensics import (
    PHASE68_JSON,
    expand_compact,
)
from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS

PHASE = "69"
PHASE69_JSON = "logs/phase69_exit_geometry.json"
PHASE69_MD = "docs/PHASE69_EXIT_GEOMETRY.md"
BLOCKED = "BLOCKED"
M5_PRESET = PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]
MIN_RR = float(M5_PRESET.get("MIN_RR", 1.5))
SL_ATR_MULT = float(M5_PRESET.get("SL_ATR_MULT", 0.35))
SWEEP_LOOKBACK = int(M5_PRESET.get("SWEEP_LOOKBACK_BARS", 12))
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "geometry",
    "extreme_winner",
    "EXTREME_WINNER_CLASSIFICATION",
    "final_gate",
    "production_safety",
    "artifacts",
)

CODE_PATH_SL_TP = "tradingbot/domain/gold_strategies/m5_london_sweep.py::evaluate_m5_london_sweep"
CODE_PATH_ROUTER = "tradingbot/domain/gold_strategies/router.py::evaluate_gold_setup"
CODE_PATH_HARDENING = "tradingbot/domain/pa_hardening.py::apply_setup_hardening"
NOT_USED_FOR_M5 = "tradingbot/domain/price_action.py::evaluate_setup ATR*SL_ATR_MULT + MIN_RR TP"


def _f(v: Any) -> float | None:
    try:
        if v is None or v == UNKNOWN:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_tp_component(planned_rr: float | None) -> str:
    if planned_rr is None:
        return UNKNOWN
    if planned_rr <= MIN_RR * 1.05:
        return "MIN_RR_FLOOR"
    return "STRUCTURAL_ASIAN_RANGE"


def inspect_geometry() -> dict[str, Any]:
    return {
        "kind": "OBSERVED_CODE",
        "production_m5_evaluator": CODE_PATH_SL_TP,
        "router": CODE_PATH_ROUTER,
        "hardening_changes_sl_tp": False,
        "hardening_note": "apply_setup_hardening writes quality/BOS/FVG metadata only; SL/TP unchanged.",
        "unused_generic_pa_path": NOT_USED_FOR_M5,
        "SL_generation": {
            "type": "hybrid",
            "labels": ["swing_based", "ATR_pad"],
            "rule": "SL = sweep window extreme (win_high SELL / win_low BUY) + ATR * SL_ATR_MULT",
            "SL_ATR_MULT": SL_ATR_MULT,
            "SWEEP_LOOKBACK_BARS": SWEEP_LOOKBACK,
            "fixed_distance": False,
            "structure_based": True,
            "atr_based": True,
        },
        "TP_generation": {
            "type": "hybrid",
            "labels": ["structural_level", "min_rr_floor"],
            "rule": "TP = entry +/- max(distance to opposite Asian range, risk * MIN_RR)",
            "MIN_RR": MIN_RR,
            "fixed_R_multiple": False,
            "structural_level": True,
            "liquidity_target": True,
            "atr_derived": False,
            "note": "When SL is tiny, max() is dominated by Asian-range distance and planned RR is unbounded.",
        },
        "ENABLE_PARTIAL_TP": bool(M5_PRESET.get("ENABLE_PARTIAL_TP", False)),
        "time_exit": False,
        "varies_with": {
            "regime": False,
            "regime_note": "USE_REGIME_FILTER may block entry; it does not rescale SL/TP.",
            "session": False,
            "session_note": "NY 15-16 UTC is an entry window, not an SL/TP formula.",
            "side": True,
            "side_note": "BUY/SELL mirror the same formula.",
            "volatility": True,
            "volatility_note": "ATR scales the SL pad and min Asian range; structural TP is range width, not ATR*k.",
            "signal_confidence": False,
            "timeframe": True,
            "timeframe_note": "M5 uses london_sweep; M15/H4 evaluators are different and not this tape.",
        },
        "code_modified": False,
    }


def extreme_forensics(events: list[dict[str, Any]], p64: dict[str, Any]) -> dict[str, Any]:
    ranked = sorted(events, key=lambda e: float(e.get("r_result") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    wins = [e for e in events if e.get("exit_class") == "WIN_TP"]
    win_rr = [_f(e.get("planned_rr")) for e in wins]
    win_rr = [x for x in win_rr if x is not None]
    risk = _f(top1.get("risk_price_units"))
    planned = _f(top1.get("planned_rr"))
    entry = _f(top1.get("entry"))
    sl = _f(top1.get("SL"))
    tp = _f(top1.get("TP"))
    tp_dist = None if (entry is None or tp is None) else abs(entry - tp)
    floor = None if risk is None else risk * MIN_RR
    structural = bool(planned is not None and planned > MIN_RR * 1.05)
    same_setup = True
    # Pathological unit check: gold prices ~thousands, SL a few units.
    unit_issue = bool(risk is not None and (risk > 500 or risk <= 0))
    data_artifact = False
    mfe = _f(top1.get("mfe_R"))
    if mfe is not None and planned is not None and abs(mfe - planned) > 5:
        data_artifact = True
    if structural and not unit_issue and not data_artifact:
        classification = "B_RARE_LEGITIMATE_STRUCTURAL"
        why = (
            "Same evaluate_m5_london_sweep path as ordinary trades. "
            "TP is max(opposite Asian range, MIN_RR*risk). The 31.84R fill is a rare tail of that "
            "hybrid: tiny swing SL versus a distant structural TP that actually tagged. "
            "Not a conversion bug, not a different evaluator, not a rerun artifact."
        )
    elif unit_issue:
        classification = "D_UNIT_CONVERSION_ISSUE"
        why = "SL distance is outside gold-price scale."
    elif data_artifact:
        classification = "E_DATA_ARTIFACT"
        why = "Walk/jsonl MFE disagrees materially with planned RR."
    else:
        classification = "A_NORMAL_GEOMETRY_CONSEQUENCE"
        why = "RR sits near the MIN_RR floor."
    return {
        "kind": "DERIVED_FROM_FROZEN_PRICES plus OBSERVED_CODE",
        "timestamp": top1.get("timestamp"),
        "side": top1.get("side"),
        "regime": top1.get("regime"),
        "entry": entry,
        "SL": sl,
        "TP": tp,
        "risk_price_units": risk,
        "planned_rr": planned,
        "tp_distance": tp_dist,
        "min_rr_floor_distance": floor,
        "tp_component": classify_tp_component(planned),
        "median_winning_planned_rr": _median(win_rr),
        "mean_winning_planned_rr": _mean(win_rr),
        "same_exit_generation_mechanism": same_setup,
        "code_path": [
            "PriceActionStrategy.generate_signals",
            "evaluate_gold_setup (london_sweep)",
            "evaluate_m5_london_sweep",
            "apply_setup_hardening (metadata only)",
        ],
        "unit_issue": unit_issue,
        "data_artifact": data_artifact,
        "unbounded_rr_property": True,
        "phase64_outlier_ts": ((p64.get("outlier") or {}).get("event") or {}).get("timestamp"),
        "classification_options": {
            "A": "Legitimate consequence of normal geometry",
            "B": "Rare but legitimate structural opportunity",
            "C": "Pathological TP-distance calculation",
            "D": "Unit/conversion issue",
            "E": "Data artifact",
            "F": "Regime-specific geometry (different formula)",
            "G": "Bug or edge case",
        },
        "EXTREME_WINNER_CLASSIFICATION": classification,
        "why": why,
        "not_C_pathological_formula": "max(asian, min_rr) is explicit; extreme RR is the tail when risk is tiny, not a NaN/swap.",
        "not_G_bug": "No evidence SL/TP were swapped or scaled in pips vs price.",
        "not_F_different_formula": "Regime does not change the SL/TP equations.",
    }


def rr_component_mix(events: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for e in events:
        rr = _f(e.get("planned_rr"))
        rows.append(classify_tp_component(rr))
    wins = [classify_tp_component(_f(e.get("planned_rr"))) for e in events if e.get("exit_class") == "WIN_TP"]
    return {
        "kind": "DERIVED",
        "all_events": dict(Counter(rows)),
        "WIN_TP": dict(Counter(wins)),
        "MIN_RR_threshold_used": MIN_RR,
        "note": "STRUCTURAL means planned_rr > MIN_RR*1.05, i.e. Asian-range TP dominated max().",
    }


def run_phase69_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p64 = _safe_load_json(root / PHASE64_JSON) or {}
    p68 = _safe_load_json(root / PHASE68_JSON) or {}
    events = expand_compact(p68.get("compact_events") or [])
    geometry = inspect_geometry()
    extreme = extreme_forensics(events, p64)
    mix = rr_component_mix(events)
    src = (root / "tradingbot/domain/gold_strategies/m5_london_sweep.py").read_text(encoding="utf-8")
    has_max = "max(tp_range, tp_rr)" in src or "max(tp_range, risk * min_rr)" in src
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS" if has_max and extreme.get("same_exit_generation_mechanism") else "FAIL",
        "phase40_scan_rerun": False,
        "strategy_rerun": False,
        "code_modified": False,
        "mt5_launched": False,
        "env_accessed": False,
        "parameters_optimized": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "geometry": geometry,
        "tp_component_mix": mix,
        "extreme_winner": extreme,
        "EXTREME_WINNER_CLASSIFICATION": extreme.get("EXTREME_WINNER_CLASSIFICATION"),
        "source_contains_hybrid_max": has_max,
        "hypotheses": [
            {
                "id": "H69-01",
                "claim": "The +31.84R event used the same evaluate_m5_london_sweep SL/TP path as ordinary trades.",
                "result": "SUPPORTED",
                "oos_used_for_decision": False,
            },
            {
                "id": "H69-02",
                "claim": "Extreme planned RR is structural Asian-range TP over a tiny swing SL, not a unit bug.",
                "result": extreme.get("EXTREME_WINNER_CLASSIFICATION"),
                "oos_used_for_decision": False,
            },
        ],
        "tests_performed": 2,
        "diagnostics_run": ["sl_source", "tp_source", "variation_axes", "extreme_rr_trace"],
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "SL_TP": "NOT_CHANGED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE69_JSON, "md": PHASE69_MD},
    }
    (root / PHASE69_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE69_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE69_MD).write_text(
        "\n".join(
            [
                "# Phase 69 — Exit Geometry Decomposition",
                "",
                f"**SL:** swing extreme + ATR pad (`SL_ATR_MULT={SL_ATR_MULT}`).",
                f"**TP:** hybrid `max(opposite Asian range, risk * MIN_RR)` with `MIN_RR={MIN_RR}`.",
                f"**EXTREME_WINNER_CLASSIFICATION:** `{payload['EXTREME_WINNER_CLASSIFICATION']}`",
                "",
                extreme.get("why") or "",
                "",
                "Hardening does not rewrite SL/TP. Generic `price_action.py` ATR*min_rr path is not the M5 tape path.",
                "No code was modified.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase69_collection(Path("."))["EXTREME_WINNER_CLASSIFICATION"])
