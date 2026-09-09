"""Phase 91 — time-to-reversal forensics.

RESEARCH ONLY. No timeout selection. Thresholds are Phase 74 CROSS_LEVELS.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _mean, _median, _utc_now
from tradingbot.backtest.phase68_exit_forensics import BAR_MINUTES
from tradingbot.backtest.phase74_profit_giveback_forensics import _f
from tradingbot.backtest.phase82_profit_protection_design import REVERSAL_BARS
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON

PHASE = "91"
PHASE91_JSON = "logs/phase91_reversal_timing_forensics.json"
PHASE91_MD = "docs/PHASE91_REVERSAL_TIMING_FORENSICS.md"
BLOCKED = "BLOCKED"
# User-requested loser MFE gates; all already in BAR_LEVELS plus 0.
LOSERS_GATES = (0.0, 0.25, 0.50, 0.75, 1.00, 1.50, 2.00)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_gate",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _times(row: dict[str, Any], lv: float) -> dict[str, Any]:
    cross = (row.get("cross") or {}).get(str(lv)) or (row.get("cross") or {}).get(f"{lv:.2f}") or {}
    if lv == 0.0:
        return {
            "time_to_first_threshold_min": 0.0 if (_f(row.get("mfe")) or 0) > 0 else None,
            "time_threshold_to_mfe_min": _f(row.get("t_mfe")),
            "time_mfe_to_exit_min": _f(row.get("t_rev")),
            "time_threshold_to_revisit_min": None,
            "time_threshold_to_exit_min": _f(row.get("hold")),
            "bars_to_threshold": None,
        }
    key = str(lv) if str(lv) in (row.get("cross") or {}) else None
    if key is None:
        for k in (row.get("cross") or {}):
            try:
                if abs(float(k) - lv) < 1e-9:
                    cross = (row.get("cross") or {})[k]
                    break
            except (TypeError, ValueError):
                continue
    return {
        "time_to_first_threshold_min": cross.get("time_to_level_min"),
        "time_threshold_to_mfe_min": cross.get("time_level_to_mfe_min"),
        "time_mfe_to_exit_min": _f(row.get("t_rev")),
        "time_threshold_to_revisit_min": cross.get("time_level_to_revisit_min"),
        "time_threshold_to_exit_min": cross.get("time_level_to_exit_min"),
        "bars_to_threshold": None
        if cross.get("time_to_level_min") is None
        else int(round(float(cross["time_to_level_min"]) / BAR_MINUTES)),
    }


def pack_times(rows: list[dict[str, Any]], lv: float) -> dict[str, Any]:
    samples = [_times(r, lv) for r in rows]
    def col(name: str) -> list[float]:
        return [float(s[name]) for s in samples if s.get(name) is not None]

    return {
        "n": len(rows),
        "median_time_to_threshold": _median(col("time_to_first_threshold_min")),
        "median_time_threshold_to_mfe": _median(col("time_threshold_to_mfe_min")),
        "median_time_mfe_to_exit": _median(col("time_mfe_to_exit_min")),
        "median_time_threshold_to_revisit": _median(col("time_threshold_to_revisit_min")),
        "median_time_threshold_to_exit": _median(col("time_threshold_to_exit_min")),
        "median_bars_to_threshold": _median([float(x) for x in col("bars_to_threshold")]),
        "pct_revisit_known": None
        if not rows
        else sum(1 for s in samples if s.get("time_threshold_to_revisit_min") is not None) / len(rows),
    }


def run_phase91_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    compact = p90.get("compact") or []
    losers = [r for r in compact if r.get("cls") == "LOSS_SL"]
    winners = [r for r in compact if r.get("cls") == "WIN_TP"]
    by_gate = {}
    for lv in LOSERS_GATES:
        if lv == 0.0:
            hit = [r for r in losers if (_f(r.get("mfe")) or 0) > 0]
        else:
            hit = [r for r in losers if (_f(r.get("mfe")) or 0) > lv]
        win_hit = (
            [r for r in winners if (_f(r.get("mfe")) or 0) > 0]
            if lv == 0.0
            else [r for r in winners if (_f(r.get("mfe")) or 0) > lv]
        )
        L = pack_times(hit, lv)
        W = pack_times(win_hit, lv)
        by_gate[str(lv)] = {
            "losers": L,
            "winners": W,
            "delta_median_mfe_to_exit": None
            if L.get("median_time_mfe_to_exit") is None or W.get("median_time_mfe_to_exit") is None
            else float(L["median_time_mfe_to_exit"]) - float(W["median_time_mfe_to_exit"]),
            "delta_median_time_to_threshold": None
            if L.get("median_time_to_threshold") is None or W.get("median_time_to_threshold") is None
            else float(L["median_time_to_threshold"]) - float(W["median_time_to_threshold"]),
        }
    # Structural kinds using predeclared FAST_MIN = 25 min, not a chosen timeout.
    fast = FAST = float(REVERSAL_BARS) * BAR_MINUTES
    def kind(r: dict[str, Any]) -> str:
        t_mfe = _f(r.get("t_mfe"))
        t_rev = _f(r.get("t_rev"))
        hold = _f(r.get("hold"))
        mfe = _f(r.get("mfe")) or 0
        if t_mfe is None:
            return "UNKNOWN"
        if t_mfe <= fast and (t_rev or 0) <= fast and mfe >= 0.5:
            return "FAST_SPIKE"
        if (r.get("bars_above") or {}).get("0.5", 0) >= REVERSAL_BARS:
            return "SUSTAINED_FAVORABLE"
        if hold is not None and hold >= 2 * fast and mfe >= 0.5:
            return "SLOW_CONTINUATION"
        if t_rev is not None and t_rev > fast:
            return "DELAYED_REVERSAL"
        return "OTHER"

    kinds_L = {}
    kinds_W = {}
    for r in losers:
        kinds_L[kind(r)] = kinds_L.get(kind(r), 0) + 1
    for r in winners:
        kinds_W[kind(r)] = kinds_W.get(kind(r), 0) + 1
    # Time as causal signal? Need a directional difference that is not a searched cutoff.
    d05 = (by_gate.get("0.5") or {}).get("delta_median_mfe_to_exit")
    time_valid = "UNSUPPORTED"
    if d05 is not None and abs(d05) >= fast:
        time_valid = "PARTIALLY_SUPPORTED"
    elif d05 is not None:
        time_valid = "WEAK_OVERLAP"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "timeout_selected": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "predeclared": {"LOSERS_GATES": LOSERS_GATES, "FAST_MIN": FAST, "REVERSAL_BARS": REVERSAL_BARS},
        "by_gate": by_gate,
        "timing_kinds_losers": kinds_L,
        "timing_kinds_winners": kinds_W,
        "TIME_AS_CAUSAL_PROTECTION_SIGNAL": time_valid,
        "note": "Phase 75 E time-exit was NEUTRAL. This phase does not pick a timeout.",
        "hypotheses": [
            {
                "id": "H91-01",
                "claim": "Loser vs winner reversal timing differs enough to justify time as a causal protection signal.",
                "result": time_valid,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["gates", "timing_kinds"],
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
        "artifacts": {"json": PHASE91_JSON, "md": PHASE91_MD},
    }
    (root / PHASE91_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE91_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 91 — Time-to-Reversal Forensics",
        "",
        "RESEARCH ONLY. No timeout chosen. Not optimal.",
        f"**TIME_AS_CAUSAL_PROTECTION_SIGNAL:** `{time_valid}`",
        "",
        f"Loser kinds: `{kinds_L}`",
        f"Winner kinds: `{kinds_W}`",
        "",
    ]
    for lv, row in by_gate.items():
        L, W = row["losers"], row["winners"]
        lines.append(
            f"- gate>{lv}R losers n=`{L.get('n')}` med_mfe_to_exit=`{L.get('median_time_mfe_to_exit')}` "
            f"winners n=`{W.get('n')}` med_mfe_to_exit=`{W.get('median_time_mfe_to_exit')}` "
            f"delta=`{row.get('delta_median_mfe_to_exit')}`"
        )
    (root / PHASE91_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase91_collection(Path("."))
    print(p["TIME_AS_CAUSAL_PROTECTION_SIGNAL"], p["timing_kinds_losers"])
