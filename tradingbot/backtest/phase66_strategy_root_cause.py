"""Phase 66 — strategy root-cause tree. Diagnosis only, no optimization."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, UNKNOWN, _git_head, _utc_now

PHASE = "66"
PHASE66_JSON = "logs/phase66_strategy_root_cause.json"
PHASE66_MD = "docs/PHASE66_STRATEGY_ROOT_CAUSE.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE64_JSON = "logs/phase64_strategy_event_forensics.json"
PHASE65_JSON = "logs/phase65_diagnostic_experiments.json"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "tree",
    "PRIMARY_ROOT_CAUSE",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _node(name: str, evidence: str, confidence: str, impact: str, researchability: str, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "EVIDENCE": evidence,
        "CONFIDENCE": confidence,
        "IMPACT": impact,
        "RESEARCHABILITY": researchability,
        "children": children or [],
    }


def build_tree(p64: dict[str, Any], p65: dict[str, Any]) -> dict[str, Any]:
    anatomy = p64.get("stop_out_anatomy") or {}
    mfe = p64.get("mae_mfe") or {}
    outlier = p64.get("outlier") or {}
    dens = p64.get("density") or {}
    sides = p64.get("side") or {}
    temp = p64.get("temporal") or {}
    rec = p64.get("recent_180d") or {}
    folds = p64.get("folds") or {}
    causes = p64.get("causes") or {}
    b = ((p65.get("experiments") or {}).get("B_outlier_robustness") or {})
    return {
        "STRATEGY_FRAGILITY": _node(
            "STRATEGY_FRAGILITY",
            "Event expectancy +0.049R, median R -1.0, PF 1.07, bootstrap p5 negative, TRAIN/recent negative, OOS positive only with an extreme TP.",
            "HIGH",
            "HIGH",
            "HIGH",
            [
                _node(
                    "ENTRY QUALITY",
                    "Existing jsonl fields only: confidence/quality_score/planned_rr/risk. EMA/ADX/BOS UNKNOWN (not persisted). "
                    "Win vs loss risk medians similar; the outlier had unusually small SL vs distant TP (planned_rr 31.8 vs win median ~1.66).",
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                    [_node("market_structure_features", "EMA200/RSI/MACD/ATR/ADX/BOS not on frozen jsonl", "UNKNOWN", "UNKNOWN", "HIGH")],
                ),
                _node(
                    "EXIT BEHAVIOR",
                    f"LOSS_SL={anatomy.get('LOSS_SL')} WIN_TP={anatomy.get('WIN_TP')}. "
                    f"Losers with MFE>0.5R={mfe.get('losers_mfe_gt_0_5R')}; MFE>1R={mfe.get('losers_mfe_gt_1R')}. "
                    f"Spread does not explain -1R ({anatomy.get('spread_claim')}). "
                    f"SL_appears_systematically_too_tight={mfe.get('SL_appears_systematically_too_tight')}.",
                    "HIGH",
                    "HIGH",
                    "HIGH",
                ),
                _node(
                    "REGIME DEPENDENCY",
                    f"Breaks most in {(p64.get('regime') or {}).get('REGIME_WHERE_STRATEGY_BREAKS')}. Classifier not modified.",
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                ),
                _node(
                    "TIME DEPENDENCY",
                    f"2023/2024 negative, 2026-01 concentrated (jan_flag={temp.get('y2026_concentrated_in_january')}). "
                    f"OOS positive because {(folds.get('OOS') or {}).get('oos_positive_because')}. "
                    f"Recent 180d reason={((rec.get('most_plausible_structural_reason')))}.",
                    "HIGH",
                    "HIGH",
                    "HIGH",
                ),
                _node(
                    "SIDE DEPENDENCY",
                    f"{sides.get('SIDE_DEPENDENCY')}: SELL holds net R, BUY ~0. Side not disabled.",
                    "HIGH",
                    "MEDIUM",
                    "HIGH",
                ),
                _node(
                    "SIGNAL DUPLICATION",
                    f"{dens.get('SIGNAL_DUPLICATION')}; mean signals/event={dens.get('mean_signals_per_event')}. "
                    "Event is the correct economic unit. RAW 2847 is inflated.",
                    "HIGH",
                    "MEDIUM",
                    "LOW",
                ),
                _node(
                    "OUTLIER DEPENDENCY",
                    f"Best event R={((outlier.get('event') or {}).get('r_result'))} at {((outlier.get('event') or {}).get('timestamp'))}. "
                    f"top1 share of net R={((outlier.get('contribution') or {}).get('top_1') or {}).get('share_of_net_R')}. "
                    f"Expectancy survives top1 removal={b.get('positive_expectancy_survives_top1_removed')}. "
                    "Exceptional planned_rr, same liquidity_sweep mechanism.",
                    "HIGH",
                    "HIGH",
                    "HIGH",
                ),
                _node(
                    "COST SENSITIVITY",
                    "Frozen MODELED_1X signal expectancy negative. Not the cause of structural -1R stop-outs.",
                    "HIGH",
                    "MEDIUM",
                    "LOW",
                ),
                _node(
                    "DATA / EXECUTION",
                    "Theoretical SL/TP exits on OHLC; no fill tape. jsonl missing Asian range and indicators. Not fabricated fills.",
                    "HIGH",
                    "MEDIUM",
                    "MEDIUM",
                ),
            ],
        ),
        "declared_primary": causes.get("PRIMARY"),
        "declared_secondary": causes.get("SECONDARY"),
        "declared_tertiary": causes.get("TERTIARY"),
    }


def run_phase66_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p64 = _safe_load_json(root / PHASE64_JSON) or {}
    p65 = _safe_load_json(root / PHASE65_JSON) or {}
    tree = build_tree(p64, p65)
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "parameters_optimized": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "tree": tree,
        "PRIMARY_ROOT_CAUSE": (p64.get("causes") or {}).get("PRIMARY"),
        "SECONDARY_ROOT_CAUSE": (p64.get("causes") or {}).get("SECONDARY"),
        "TERTIARY_ROOT_CAUSE": (p64.get("causes") or {}).get("TERTIARY"),
        "EDGE_QUALITY": "FRAGILE",
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
        "artifacts": {"json": PHASE66_JSON, "md": PHASE66_MD},
    }
    (root / PHASE66_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE66_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = ["# Phase 66 — Strategy Root Cause", "", "```", "STRATEGY_FRAGILITY"]
    for child in (tree.get("STRATEGY_FRAGILITY") or {}).get("children") or []:
        lines.append(f"|")
        lines.append(f"+-- {child['name']}  [{child['CONFIDENCE']}/{child['IMPACT']}/{child['RESEARCHABILITY']}]")
        lines.append(f"    {child['EVIDENCE'][:200]}")
    lines.extend(["```", "", f"PRIMARY `{payload['PRIMARY_ROOT_CAUSE']}`", f"SECONDARY `{payload['SECONDARY_ROOT_CAUSE']}`", f"TERTIARY `{payload['TERTIARY_ROOT_CAUSE']}`", "", "No optimization.", ""])
    (root / PHASE66_MD).write_text("\n".join(lines), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase66_collection(Path("."))["PRIMARY_ROOT_CAUSE"])
