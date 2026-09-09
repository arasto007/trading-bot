"""Phase 99 — path velocity / persistence at first-favorable states.

RESEARCH ONLY. Uses Phase 98 causal snapshots. Not a protection rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase82_profit_protection_design import REVERSAL_BARS
from tradingbot.backtest.phase90_profit_giveback_path_forensics import FAST_MIN
from tradingbot.backtest.phase98_first_favorable_state import (
    CD,
    EF,
    PHASE98_JSON,
    STATE_LEVELS,
    _rate,
    confirmed_sep,
    majority_sep,
)

PHASE = "99"
PHASE99_JSON = "logs/phase99_path_velocity_persistence.json"
PHASE99_MD = "docs/PHASE99_PATH_VELOCITY_PERSISTENCE.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_level",
    "final_gate",
    "production_safety",
    "artifacts",
)


def persist_kind(s: dict[str, Any]) -> str:
    bars = int(s.get("bars_elapsed") or 0)
    cons = int(s.get("cons_fav_extreme") or 0)
    if s.get("fast") and s.get("vel_ge_cut"):
        return "FAST_SPIKE"
    if cons >= REVERSAL_BARS or (bars >= REVERSAL_BARS and not s.get("fast")):
        return "SUSTAINED_FAVORABLE"
    return "MIXED"


def run_phase99_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    compact = p98.get("compact") or []
    by_level = {}
    separators = []
    for lv in STATE_LEVELS:
        key = str(lv)
        rows = []
        for r in compact:
            s = (r.get("states") or {}).get(key)
            if not s:
                continue
            kind = persist_kind(s)
            rows.append(
                {
                    **s,
                    "path_class": r.get("path_class"),
                    "fold": r.get("fold"),
                    "persist_kind": kind,
                    "is_fast_spike": kind == "FAST_SPIKE",
                    "is_sustained": kind == "SUSTAINED_FAVORABLE",
                    "is_mixed": kind == "MIXED",
                    "fav_bar_frac": None
                    if not s.get("bars_elapsed")
                    else (s.get("n_fav_bars") or 0) / float(s["bars_elapsed"]),
                    "ts": r.get("ts"),
                }
            )
        cd = [x for x in rows if x.get("path_class") in CD]
        ef = [x for x in rows if x.get("path_class") in EF]
        feats = ("is_fast_spike", "is_sustained", "is_mixed", "fast", "vel_ge_cut")
        feat_rows = {}
        for feat in feats:
            cd_r = _rate(cd, feat)
            ef_r = _rate(ef, feat)

            def fold_sep(fold: str, f=feat) -> str:
                return majority_sep(
                    _rate([x for x in cd if x.get("fold") == fold], f).get("rate"),
                    _rate([x for x in ef if x.get("fold") == fold], f).get("rate"),
                )

            tr, va = fold_sep("TRAIN"), fold_sep("VALIDATION")
            confirmed = confirmed_sep(
                _rate([x for x in cd if x.get("fold") == "TRAIN"], feat).get("rate"),
                _rate([x for x in ef if x.get("fold") == "TRAIN"], feat).get("rate"),
                _rate([x for x in cd if x.get("fold") == "VALIDATION"], feat).get("rate"),
                _rate([x for x in ef if x.get("fold") == "VALIDATION"], feat).get("rate"),
            )
            feat_rows[feat] = {
                "CD": cd_r,
                "EF": ef_r,
                "FULL_sep": majority_sep(cd_r.get("rate"), ef_r.get("rate")),
                "TRAIN_sep": tr,
                "VAL_sep": va,
                "TRAIN_VAL_confirmed": confirmed,
            }
            if confirmed:
                separators.append({"level": lv, "feature": feat})
        by_level[key] = {
            "n": len(rows),
            "n_CD": len(cd),
            "n_EF": len(ef),
            "kinds_CD": {
                k: sum(1 for x in cd if x.get("persist_kind") == k) for k in ("FAST_SPIKE", "SUSTAINED_FAVORABLE", "MIXED")
            },
            "kinds_EF": {
                k: sum(1 for x in ef if x.get("persist_kind") == k) for k in ("FAST_SPIKE", "SUSTAINED_FAVORABLE", "MIXED")
            },
            "features": feat_rows,
        }
    verdict = "OVERLAPPING_DESCRIPTIVE" if not separators else "CANDIDATE_PERSISTENCE"
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
        "predeclared": {"FAST_MIN": FAST_MIN, "REVERSAL_BARS": REVERSAL_BARS},
        "by_level": by_level,
        "separators_train_val": separators,
        "PERSISTENCE_DISCRIMINATOR": verdict,
        "evidence_kind": "FROZEN-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H99-01",
                "claim": "How MFE was achieved (spike vs sustained) separates C/D from E/F on TRAIN and VAL.",
                "result": verdict,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["persist_kinds"],
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
        "artifacts": {"json": PHASE99_JSON, "md": PHASE99_MD},
    }
    (root / PHASE99_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE99_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE99_MD).write_text(
        "\n".join(
            [
                "# Phase 99 — Path Velocity / Persistence",
                "",
                "FROZEN-DATA-EVIDENCE. Persistence kinds use predeclared REVERSAL_BARS / unique-half velocity. Not a rule.",
                f"**PERSISTENCE_DISCRIMINATOR:** `{verdict}`",
                f"TRAIN+VAL separators: `{separators}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase99_collection(Path("."))
    print(p["PERSISTENCE_DISCRIMINATOR"], p["separators_train_val"])
