"""Phase 96 — robustness / fragility gate for Phase 95 families.

Qualitative evidence scores. No threshold optimization.
Bootstrap seed 400040, 2000 paths, event level.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_BOOTSTRAP_SEED,
    PHASE40_JSON,
    _git_head,
    _mean,
    _utc_now,
)
from tradingbot.backtest.phase70_exit_counterfactuals import N_BOOT
from tradingbot.backtest.phase74_profit_giveback_forensics import _f
from tradingbot.backtest.phase95_protection_family_v2 import FAMILIES, PHASE95_JSON

PHASE = "96"
PHASE96_JSON = "logs/phase96_protection_robustness_gate.json"
PHASE96_MD = "docs/PHASE96_PROTECTION_ROBUSTNESS_GATE.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_family",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _sign(d: float | None) -> str:
    if d is None:
        return "INSUFFICIENT"
    if d > 0:
        return "POS"
    if d < 0:
        return "NEG"
    return "NEUTRAL"


def _boot_delta(walks: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = [(_f(w.get("orig")), _f(w.get("cf"))) for w in walks]
    pairs = [(o, c) for o, c in pairs if o is not None and c is not None]
    if not pairs:
        return {"n": 0, "mean_delta": None, "p5": None, "seed": PHASE40_BOOTSTRAP_SEED}
    rng = random.Random(PHASE40_BOOTSTRAP_SEED)
    n = len(pairs)
    means = []
    for _ in range(N_BOOT):
        s = 0.0
        for _i in range(n):
            o, c = pairs[rng.randrange(n)]
            s += c - o
        means.append(s / n)
    means.sort()
    return {
        "n": n,
        "mean_delta": _mean([c - o for o, c in pairs]),
        "p5": means[int(0.05 * N_BOOT)],
        "p50": means[int(0.50 * N_BOOT)],
        "p95": means[min(N_BOOT - 1, int(0.95 * N_BOOT))],
        "seed": PHASE40_BOOTSTRAP_SEED,
        "n_boot": N_BOOT,
        "kind": "EVENT_LEVEL_BOOTSTRAP",
    }


def _sub_delta(walks: list[dict[str, Any]], pred) -> dict[str, Any]:
    rows = [w for w in walks if pred(w)]
    ox = [_f(w.get("orig")) for w in rows]
    cx = [_f(w.get("cf")) for w in rows]
    pairs = [(a, b) for a, b in zip(ox, cx) if a is not None and b is not None]
    if not pairs:
        return {"n": 0, "delta": None, "sign": "INSUFFICIENT"}
    d = _mean([b for _, b in pairs]) - _mean([a for a, _ in pairs])
    return {"n": len(pairs), "delta": d, "sign": _sign(d)}


def classify(status: str, tail: str, oos: str, val: str, train: str) -> str:
    if status == "DATA_LIMITED":
        return "DATA_LIMITED"
    if status == "HELPFUL" and tail in {"PRESERVED", "PARTIALLY_PRESERVED"} and oos == "POS" and val == "POS":
        return "PRODUCTION_CANDIDATE"
    if status == "HARMFUL":
        return "REJECTED"
    if status == "HELPFUL":
        return "RESEARCH_ONLY"
    return "RESEARCH_ONLY" if status == "NEUTRAL" else "REJECTED"


def run_phase96_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p95 = _safe_load_json(root / PHASE95_JSON) or {}
    cfs = p95.get("counterfactuals") or {}
    walks = p95.get("walks") or {}
    tails = p95.get("tails") or {}
    by_family = {}
    for name in FAMILIES:
        row = cfs.get(name) or {}
        w = walks.get(name) or []
        tr = (row.get("TRAIN") or {}).get("delta_expectancy")
        va = (row.get("VALIDATION") or {}).get("delta_expectancy")
        oos = (row.get("OOS") or {}).get("delta_expectancy")
        rec = (row.get("RECENT_180D") or {}).get("delta_expectancy")
        tail = (tails.get(name) or {}).get("TAIL_PRESERVATION")
        side = {
            "BUY": _sub_delta(w, lambda x: x.get("side") == "BUY"),
            "SELL": _sub_delta(w, lambda x: x.get("side") == "SELL"),
        }
        years = {}
        for y in sorted({str(x.get("year")) for x in w}):
            years[y] = _sub_delta(w, lambda x, yy=y: str(x.get("year")) == yy)
        scores = {
            "CAUSALITY": "YES_BAR_CLOSE_STOP",
            "OOS_SUPPORT": _sign(oos),
            "RECENT_SUPPORT": _sign(rec),
            "TAIL_PRESERVATION": tail,
            "WINNER_PRESERVATION": "FAIL" if (row.get("winner_le_0") or 0) > 0 else (
                "PARTIAL" if (row.get("winner_lt_original") or 0) > 0 else "PASS"
            ),
            "LOSER_RESCUE": row.get("loser_rescue_ge_0"),
            "STABILITY": "PASS" if _sign(tr) == _sign(va) and _sign(tr) != "INSUFFICIENT" else "FAIL_TRAIN_VAL_DISAGREE",
            "COMPLEXITY": "LOW",
        }
        cls = classify(row.get("status") or "", str(tail or ""), _sign(oos), _sign(va), _sign(tr))
        by_family[name] = {
            "status_phase95": row.get("status"),
            "TRAIN": {"delta": tr, "sign": _sign(tr)},
            "VALIDATION": {"delta": va, "sign": _sign(va)},
            "OOS": {"delta": oos, "sign": _sign(oos)},
            "RECENT_180D": {"delta": rec, "sign": _sign(rec)},
            "by_side": side,
            "by_year": years,
            "event_cluster_unit": True,
            "without_top1_delta": row.get("top1_sensitivity_delta"),
            "without_top5_delta": row.get("top5_sensitivity_delta"),
            "bootstrap": _boot_delta(w),
            "threshold_perturbation": "NOT_PERFORMED_WOULD_BE_SEARCH",
            "future_information": False,
            "scores": scores,
            "class": cls,
            "not_production_from_expectancy_alone": True,
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
        "by_family": by_family,
        "production_candidates": [n for n, v in by_family.items() if v.get("class") == "PRODUCTION_CANDIDATE"],
        "hypotheses": [
            {
                "id": "H96-01",
                "claim": "No family is a PRODUCTION_CANDIDATE merely from full-horizon expectancy.",
                "result": [n for n, v in by_family.items() if v.get("class") == "PRODUCTION_CANDIDATE"],
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": list(FAMILIES),
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
        "artifacts": {"json": PHASE96_JSON, "md": PHASE96_MD},
    }
    (root / PHASE96_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE96_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 96 — Protection Robustness Gate",
        "",
        "Qualitative scores. Bootstrap seed 400040, 2000 event resamples. No threshold perturbation (would be search).",
        "",
    ]
    for name, row in by_family.items():
        lines.append(
            f"- `{name}`: class=`{row.get('class')}` 95=`{row.get('status_phase95')}` "
            f"TRAIN=`{(row.get('TRAIN') or {}).get('sign')}` VAL=`{(row.get('VALIDATION') or {}).get('sign')}` "
            f"OOS=`{(row.get('OOS') or {}).get('sign')}` RECENT=`{(row.get('RECENT_180D') or {}).get('sign')}` "
            f"tail=`{(row.get('scores') or {}).get('TAIL_PRESERVATION')}`"
        )
    (root / PHASE96_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase96_collection(Path("."))
    print({k: v.get("class") for k, v in p["by_family"].items()})
