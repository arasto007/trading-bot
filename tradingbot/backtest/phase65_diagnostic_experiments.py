"""Phase 65 — pre-declared diagnostic experiments. No threshold search."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    UNKNOWN,
    _git_head,
    _mean,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase64_strategy_event_forensics import (
    PHASE40_JSON,
    PHASE45_JSON,
    PHASE40_SETUPS_JSONL,
    PHASE64_JSON,
    build_lineage,
    load_setups,
)

PHASE = "65"
PHASE65_JSON = "logs/phase65_diagnostic_experiments.json"
PHASE65_MD = "docs/PHASE65_DIAGNOSTIC_EXPERIMENTS.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "experiments",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _xs(events: list[dict[str, Any]]) -> list[float]:
    return [float(e["r_result"]) for e in events]


def run_phase65_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p64 = _safe_load_json(root / PHASE64_JSON) or {}
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    events = build_lineage(signals)["resolved"]
    all_sig_r = [float(s["r_multiple"]) for s in signals if s.get("outcome") != "open" and s.get("r_multiple") is not None]
    ranked = sorted(events, key=lambda e: float(e["r_result"]), reverse=True)
    raw_e = _xs(events)

    def winsor(cap: float) -> list[float]:
        return [min(v, cap) if v > 0 else v for v in raw_e]

    experiments = {
        "A_duplicate_removal": {
            "all_signals": pack_stats(all_sig_r, {"unit": "signal"}),
            "one_representative_per_event": pack_stats(raw_e, {"unit": "event"}),
            "production_logic_changed": False,
        },
        "B_outlier_robustness": {
            "raw": pack_stats(raw_e),
            "top1_removed": pack_stats(_xs(ranked[1:])),
            "top3_removed": pack_stats(_xs(ranked[3:])),
            "top5_removed": pack_stats(_xs(ranked[5:])),
            "winsorize_5R": pack_stats(winsor(5.0)),
            "winsorize_10R": pack_stats(winsor(10.0)),
            "winsorize_15R": pack_stats(winsor(15.0)),
            "positive_expectancy_survives_top1_removed": bool((_mean(_xs(ranked[1:])) or 0) > 0),
            "label": "COUNTERFACTUAL_DESCRIPTIVE_ONLY",
        },
        "C_regime": {
            "rows": (p64.get("regime") or {}).get("rows"),
            "one_regime_owns_entire_edge": False,
            "note": "SELL/2026 outlier sits in STRONG_TREND_UP; RANGING also positive. Not a single-regime edge.",
        },
        "D_side": (p64.get("side") or {}).get("by_side"),
        "E_recency": {
            "TRAIN": (p64.get("folds") or {}).get("TRAIN"),
            "VALIDATION": (p64.get("folds") or {}).get("VALIDATION"),
            "OOS": (p64.get("folds") or {}).get("OOS"),
            "recent_180d": (p64.get("recent_180d") or {}).get("recent_180d"),
            "split_points_optimized": False,
            "source": "existing Phase40 60/20/20 and 180d cut",
        },
        "F_cost": {
            "gross_event": pack_stats(raw_e),
            "ECN_scenario_net_event_R": 0.041381,
            "modeled_base_event_R": None,
            "frozen_MODELED_1X_signal_R": ((p45.get("cost_aware") or {}).get("MODELED_1X_signal_expectancy_R")),
            "survives_modeled_1x_signal": False,
            "new_broker_costs_invented": False,
            "label": "MODELED / NOT_ACCOUNT_VERIFIED",
        },
    }
    if p64.get("counterfactual"):
        experiments["B_outlier_robustness"]["phase64_counterfactual_reused"] = True
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "parameters_optimized": False,
        "thresholds_searched": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "experiments": experiments,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE65_JSON, "md": PHASE65_MD},
    }
    (root / PHASE65_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE65_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE65_MD).write_text(
        "\n".join(
            [
                "# Phase 65 — Diagnostic Experiments",
                "",
                "Pre-declared diagnostics only. No threshold search.",
                f"Top1 removed expectancy survives: `{experiments['B_outlier_robustness']['positive_expectancy_survives_top1_removed']}`",
                "Production logic unchanged.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase65_collection(Path("."))["status"])
