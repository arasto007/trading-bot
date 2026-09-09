"""Phase 100 — retracement-then-expansion vs retracement-then-failure.

Labels use eventual outcome. Features use only bars up to the retrace bar.
+31.84R event is kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _median, _utc_now
from tradingbot.backtest.phase68_exit_forensics import EXTREME_R
from tradingbot.backtest.phase74_profit_giveback_forensics import _f
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON
from tradingbot.backtest.phase98_first_favorable_state import CD, EF, PHASE98_JSON, _rate, confirmed_sep, majority_sep

PHASE = "100"
PHASE100_JSON = "logs/phase100_retrace_expansion_forensics.json"
PHASE100_MD = "docs/PHASE100_RETRACE_EXPANSION_FORENSICS.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "cohorts",
    "final_gate",
    "production_safety",
    "artifacts",
)


def label_after(orig: float | None, path_class: str | None) -> str:
    if orig is None:
        return "UNKNOWN"
    if orig >= EXTREME_R or path_class == "F":
        return "EXTREME_CONTINUATION"
    if orig > 0:
        return "ORDINARY_WIN"
    return "FAILURE"


def run_phase100_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    compact = p98.get("compact") or []
    ranked = sorted(compact, key=lambda r: float(r.get("orig") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    rows = []
    for r in compact:
        ret = (r.get("anatomy") or {}).get("retrace")
        if not ret:
            continue
        lab = label_after(_f(r.get("orig")), r.get("path_class"))
        s05 = (r.get("states") or {}).get("0.5") or {}
        rows.append(
            {
                "ts": r.get("ts"),
                "path_class": r.get("path_class"),
                "fold": r.get("fold"),
                "orig": r.get("orig"),
                "label": lab,
                "wick_reject": ret.get("wick_reject"),
                "close_against": ret.get("close_against"),
                "range_expand": ret.get("range_expand"),
                "failed_new_extreme": ret.get("failed_new_extreme"),
                "cons_adv_ge_2": int(ret.get("cons_adv_close") or 0) >= 2,
                "fast_to_half": bool(s05.get("fast")),
                "wick_only_at_half": bool(s05.get("wick_only")),
                "is_CD": r.get("path_class") in CD,
                "is_EF": r.get("path_class") in EF,
            }
        )
    fail = [x for x in rows if x.get("label") == "FAILURE"]
    win = [x for x in rows if x.get("label") == "ORDINARY_WIN"]
    ext = [x for x in rows if x.get("label") == "EXTREME_CONTINUATION"]
    cd = [x for x in rows if x.get("is_CD")]
    ef = [x for x in rows if x.get("is_EF")]
    feats = ("wick_reject", "close_against", "range_expand", "failed_new_extreme", "cons_adv_ge_2", "fast_to_half")
    feat_rows = {}
    separators = []
    for feat in feats:
        cd_r, ef_r = _rate(cd, feat), _rate(ef, feat)

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
            "FAIL": _rate(fail, feat),
            "WIN": _rate(win, feat),
            "EXT": _rate(ext, feat),
            "TRAIN_sep": tr,
            "VAL_sep": va,
            "TRAIN_VAL_confirmed": confirmed,
        }
        if confirmed:
            separators.append(feat)
    disc = "NOT_ESTABLISHED" if not separators else "AT_RETRACE_CANDIDATE"
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
        "n_with_retrace": len(rows),
        "cohorts": {
            "FAILURE": {"n": len(fail), "median_R": _median([_f(x.get("orig")) for x in fail if _f(x.get("orig")) is not None])},
            "ORDINARY_WIN": {"n": len(win)},
            "EXTREME_CONTINUATION": {"n": len(ext)},
        },
        "features": feat_rows,
        "separators_train_val": separators,
        "PRE_RETRACE_DISCRIMINATOR": disc,
        "outlier_kept": True,
        "outlier_ts": top1.get("ts"),
        "outlier_in_retrace_set": any(x.get("ts") == top1.get("ts") for x in rows),
        "evidence_kind": "FROZEN-DATA-EVIDENCE",
        "label_kind": "COUNTERFACTUAL_LABEL_ONLY",
        "hypotheses": [
            {
                "id": "H100-01",
                "claim": "At-retrace structure available before continuation/failure separates C/D from E/F on TRAIN and VAL.",
                "result": disc,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["retrace_cohorts"],
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
            "baseline_rewritten": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE100_JSON, "md": PHASE100_MD},
    }
    (root / PHASE100_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE100_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE100_MD).write_text(
        "\n".join(
            [
                "# Phase 100 — Retracement then Expansion vs Failure",
                "",
                "FROZEN-DATA-EVIDENCE. Outcome labels are not features. Outlier kept.",
                f"**PRE_RETRACE_DISCRIMINATOR:** `{disc}` n_retrace=`{len(rows)}`",
                f"FAILURE n=`{len(fail)}` ORDINARY_WIN n=`{len(win)}` EXTREME n=`{len(ext)}`",
                f"TRAIN+VAL separators: `{separators}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase100_collection(Path("."))
    print(p["PRE_RETRACE_DISCRIMINATOR"], p["cohorts"])
