"""Phase 82 — profit-protection design taxonomy.

RESEARCH ONLY. No walks, no parameters searched, no production change.
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
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import load_frozen_ohlc
from tradingbot.backtest.phase81_exit_research_gate import PHASE81_JSON

PHASE = "82"
PHASE82_JSON = "logs/phase82_profit_protection_design.json"
PHASE82_MD = "docs/PHASE82_PROFIT_PROTECTION_DESIGN.md"
BLOCKED = "BLOCKED"
# Unique structural half — not searched among 0.3/0.4/0.6.
STRUCTURAL_FRACTION = 0.5
# Predeclared from Phase 68/74 L3 (LOSS_AFTER_0.5R).
MEANINGFUL_MFE_R = 0.5
# Predeclared from Phase 68 median MFE-to-SL.
REVERSAL_BARS = 5
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "taxonomy",
    "final_gate",
    "production_safety",
    "artifacts",
)


def run_phase82_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p81 = _safe_load_json(root / PHASE81_JSON) or {}
    df, _fp = load_frozen_ohlc(root)
    cols = list(df.columns) if df is not None else []
    has_atr = any(str(c).lower() == "atr" for c in cols)
    has_ohlc = all(c in cols for c in ("open", "high", "low", "close")) if cols else False
    taxonomy = {
        "A_MFE_PERCENTAGE_PROTECTION": {
            "causal_rationale": (
                "Naive BE floors at 0R regardless of how far price went. "
                f"A unique structural half ({STRUCTURAL_FRACTION}) of running MFE ratchets a floor "
                "that stays inside open profit, so a 32R peak would floor near 16R rather than 0R."
            ),
            "predeclared": {
                "trigger_MFE_R": MEANINGFUL_MFE_R,
                "fraction": STRUCTURAL_FRACTION,
                "source": "L3 LOSS_AFTER_0.5R; unique half of [0,MFE]; not searched",
            },
            "required_data": ["entry", "SL/risk", "OHLC path after entry"],
            "available_data": ["jsonl entry/SL/TP", "frozen M5 OHLC"],
            "unavailable_data": [],
            "right_tail_risk": "If the +31.84R path retraced through 0.5*MFE after first arming, the tail is cut. Diagnostic, not a reason to retune fraction.",
            "testable_on_frozen_tape": True,
            "parameter_unresolved": False,
        },
        "B_PEAK_TO_CURRENT_RETRACEMENT": {
            "causal_rationale": (
                "Giveback is peak-to-SL surrender. Exit when half of peak MFE is given back. "
                f"Trigger MFE>={MEANINGFUL_MFE_R}R from L3. Half is the unique structural fraction. "
                f"5-bar anatomy remains a TIME concept (Phase 75 E was NEUTRAL) and is not mixed in unless A and B independently help."
            ),
            "predeclared": {
                "trigger_MFE_R": MEANINGFUL_MFE_R,
                "retrace_fraction_of_peak": STRUCTURAL_FRACTION,
                "source": "same unique half; reversal anatomy motivates diagnosing retrace, not a 10/15/20/25 search",
            },
            "required_data": ["running MFE from OHLC", "current adverse extreme"],
            "available_data": ["frozen M5 OHLC"],
            "unavailable_data": ["true intrabar order inside a bar"],
            "right_tail_risk": "Same-bar MFE+retrace is AMBIGUOUS (conservative floor-first).",
            "testable_on_frozen_tape": True,
            "parameter_unresolved": False,
            "note": "On a stop interpretation this coincides with trailing 50% of running MFE. Phase 83 therefore tests trailing peak-retrace as PEAK_RETRACE_EXIT and a non-trailing one-shot half-lock as MFE_FRACTION_FLOOR.",
        },
        "C_STRUCTURAL_SWING_PROTECTION": {
            "causal_rationale": "Protect behind an already-confirmed in-trade swing (BUY below confirmed swing low, SELL above confirmed swing high) after meaningful MFE.",
            "predeclared": {
                "confirmation": "1 already-closed bar on each side of the pivot (no future bar)",
                "trigger_MFE_R": MEANINGFUL_MFE_R,
            },
            "required_data": ["OHLC after entry"],
            "available_data": ["frozen M5 OHLC"],
            "unavailable_data": ["persisted strategy swings/BOS on jsonl"],
            "right_tail_risk": "Early confirmed swings near entry can act like a tight trail and clip extensions.",
            "testable_on_frozen_tape": bool(has_ohlc),
            "parameter_unresolved": False,
            "invented_detector": False,
        },
        "D_VOLATILITY_NORMALIZED_PROTECTION": {
            "causal_rationale": "Retrace thresholds in R ignore changing ATR. Normalization would need ATR known at the event bar.",
            "required_data": ["ATR at or before entry timestamp"],
            "available_data": [],
            "unavailable_data": ["atr column on frozen parquet", "ATR on jsonl"],
            "right_tail_risk": UNKNOWN,
            "testable_on_frozen_tape": False,
            "parameter_unresolved": True,
            "status": "DATA_LIMITED",
            "note": "Parquet columns are OHLC+volume only. Computing a new ATR series would introduce ATR_PERIOD (new parameter). Forbidden.",
        },
        "E_HYBRID": {
            "causal_rationale": "Combine only if two families independently show TRAIN+VAL HELPFUL without parameter search.",
            "required_data": ["results of A-D tests"],
            "available_data": ["Phase 83 outcomes"],
            "unavailable_data": [],
            "right_tail_risk": "Compounded clipping.",
            "testable_on_frozen_tape": "conditional",
            "created_automatically": False,
            "parameter_unresolved": False,
        },
    }
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "parquet_columns": cols,
        "atr_on_tape": has_atr,
        "ohlc_on_tape": has_ohlc,
        "STRUCTURAL_FRACTION": STRUCTURAL_FRACTION,
        "MEANINGFUL_MFE_R": MEANINGFUL_MFE_R,
        "REVERSAL_BARS": REVERSAL_BARS,
        "naive_BE_rejected": True,
        "naive_BE_reason": p81.get("BEST_STRUCTURAL_COUNTERFACTUAL"),
        "taxonomy": taxonomy,
        "hypotheses": [
            {
                "id": "H82-01",
                "claim": "A unique half-of-MFE floor is a structural alternative to naive BE, testable on frozen OHLC; ATR is not on tape.",
                "result": "TAXONOMY_READY",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["taxonomy_A_E", "atr_availability"],
        "oos_used_for_selection": False,
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
        "artifacts": {"json": PHASE82_JSON, "md": PHASE82_MD},
    }
    (root / PHASE82_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE82_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 82 — Profit-Protection Design Taxonomy",
        "",
        "RESEARCH ONLY. No walks in this phase. No parameter search. Production unchanged.",
        "",
        f"Predeclared: trigger MFE>={MEANINGFUL_MFE_R}R (Phase 74 L3 LOSS_AFTER_0.5R); "
        f"fraction={STRUCTURAL_FRACTION} (unique half of [0, MFE], not searched among 0.3/0.4/0.6).",
        f"Reversal anatomy (25 min / {REVERSAL_BARS} M5 bars) motivates diagnosing retracement, not a bar-count search.",
        f"ATR on frozen parquet: `{has_atr}` (columns={cols}). Family D = DATA_LIMITED.",
        "Naive BE/lock remain rejected from Phase 75. Hybrid is not created automatically.",
        "",
    ]
    titles = {
        "A_MFE_PERCENTAGE_PROTECTION": "A. MFE-percentage protection",
        "B_PEAK_TO_CURRENT_RETRACEMENT": "B. Peak-to-current retracement protection",
        "C_STRUCTURAL_SWING_PROTECTION": "C. Structural swing protection",
        "D_VOLATILITY_NORMALIZED_PROTECTION": "D. Volatility-normalized protection",
        "E_HYBRID": "E. Hybrid protection",
    }
    for key, title in titles.items():
        row = taxonomy[key]
        md.extend(
            [
                f"## {title}",
                "",
                f"- Causal rationale: {row.get('causal_rationale')}",
                f"- Required data: {row.get('required_data')}",
                f"- Available data: {row.get('available_data')}",
                f"- Unavailable data: {row.get('unavailable_data')}",
                f"- Right-tail risk: {row.get('right_tail_risk')}",
                f"- Testable on frozen tape: {row.get('testable_on_frozen_tape')}",
                f"- Parameter unresolved: {row.get('parameter_unresolved')}",
                "",
            ]
        )
    (root / PHASE82_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase82_collection(Path("."))["atr_on_tape"])
