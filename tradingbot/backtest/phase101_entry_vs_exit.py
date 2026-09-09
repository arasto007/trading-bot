"""Phase 101 — entry quality vs exit failure.

Are C/D losers distinguishable at entry / first bars, or is EXIT still dominant?
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase98_first_favorable_state import CD, EF, PHASE98_JSON, _rate, confirmed_sep, majority_sep

PHASE = "101"
PHASE101_JSON = "logs/phase101_entry_vs_exit.json"
PHASE101_MD = "docs/PHASE101_ENTRY_VS_EXIT.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "ENTRY_DISTINGUISHABLE",
    "final_gate",
    "production_safety",
    "artifacts",
)


def run_phase101_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    compact = p98.get("compact") or []
    rows = []
    for r in compact:
        anat = r.get("anatomy") or {}
        rows.append(
            {
                "ts": r.get("ts"),
                "path_class": r.get("path_class"),
                "fold": r.get("fold"),
                "side": r.get("side"),
                "reg": r.get("reg"),
                "n_sig": r.get("n_sig"),
                "fav_before_adv": anat.get("fav_before_adv"),
                "same_bar_fav_adv": bool(anat.get("same_bar_fav_adv")),
                "fav_first": anat.get("fav_before_adv") is True,
                "adv_first": anat.get("fav_before_adv") is False,
                "order_ambiguous": anat.get("fav_before_adv") == "AMBIGUOUS",
                "cluster_ge_median": (r.get("n_sig") or 0) >= 6,  # Phase 94 median 6, not searched
                "is_CD": r.get("path_class") in CD,
                "is_EF": r.get("path_class") in EF,
                "is_A": r.get("path_class") == "A",
            }
        )
    cd = [x for x in rows if x.get("is_CD")]
    ef = [x for x in rows if x.get("is_EF")]
    a_only = [x for x in rows if x.get("is_A")]
    feats = ("fav_first", "adv_first", "order_ambiguous", "cluster_ge_median")
    feat_rows = {}
    separators = []
    for feat in feats:
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
            "CD": _rate(cd, feat),
            "EF": _rate(ef, feat),
            "A": _rate(a_only, feat),
            "TRAIN_sep": tr,
            "VAL_sep": va,
            "TRAIN_VAL_confirmed": confirmed,
        }
        if confirmed:
            separators.append(feat)
    entry_dist = bool(separators)
    if entry_dist:
        problem = "PARTLY_SIGNAL_QUALITY"
    else:
        problem = "EXIT_REMAINS_DOMINANT"
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
        "n_CD": len(cd),
        "n_EF": len(ef),
        "n_A_immediate": len(a_only),
        "features": feat_rows,
        "separators_train_val": separators,
        "ENTRY_DISTINGUISHABLE": entry_dist,
        "PROBLEM": problem,
        "signal_generation_unchanged": True,
        "evidence_kind": "FROZEN-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H101-01",
                "claim": "C/D losers are distinguishable at entry from E/F winners.",
                "result": "SUPPORTED" if entry_dist else "UNSUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["path_order", "cluster_at_entry"],
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
        "artifacts": {"json": PHASE101_JSON, "md": PHASE101_MD},
    }
    (root / PHASE101_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE101_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE101_MD).write_text(
        "\n".join(
            [
                "# Phase 101 — Entry Quality vs Exit Failure",
                "",
                "FROZEN-DATA-EVIDENCE. Signal generation not altered.",
                f"**ENTRY_DISTINGUISHABLE:** `{entry_dist}`",
                f"**PROBLEM:** `{problem}`",
                f"A (immediate adverse) n=`{len(a_only)}` is the only class that is structurally an entry/path-start failure.",
                f"TRAIN+VAL separators C/D vs E/F: `{separators}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase101_collection(Path("."))
    print(p["ENTRY_DISTINGUISHABLE"], p["PROBLEM"])
