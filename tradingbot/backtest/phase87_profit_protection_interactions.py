"""Phase 87 — side / session / time interaction diagnosis.

No side-specific or session-specific parameters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, UNKNOWN, _git_head, _mean, _utc_now
from tradingbot.backtest.phase74_profit_giveback_forensics import _f
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, TESTABLE_FAMILIES
from tradingbot.backtest.phase86_profit_protection_oos import PHASE86_JSON

PHASE = "87"
PHASE87_JSON = "logs/phase87_profit_protection_interactions.json"
PHASE87_MD = "docs/PHASE87_PROFIT_PROTECTION_INTERACTIONS.md"
BLOCKED = "BLOCKED"
MIN_N = 8
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "by_family",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _group_delta(walks: list[dict[str, Any]], key: str) -> dict[str, Any]:
    g: dict[str, list[tuple[float, float]]] = {}
    for w in walks:
        o, c = _f(w.get("orig")), _f(w.get("cf"))
        if o is None or c is None:
            continue
        g.setdefault(str(w.get(key) or UNKNOWN), []).append((o, c))
    out = {}
    for k, pairs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        ox = [a for a, _ in pairs]
        cx = [b for _, b in pairs]
        d = _mean(cx) - _mean(ox)
        out[k] = {
            "n": len(pairs),
            "small_n": len(pairs) < MIN_N,
            "orig_exp": _mean(ox),
            "cf_exp": _mean(cx),
            "delta_exp": d,
            "sign": "POS" if d > 0 else ("NEG" if d < 0 else "NEUTRAL"),
        }
    return out


def classify_interaction(by_side: dict, by_sess: dict, by_hour: dict) -> dict[str, Any]:
    buy = (by_side.get("BUY") or {}).get("sign")
    sell = (by_side.get("SELL") or {}).get("sign")
    buy_n = (by_side.get("BUY") or {}).get("n") or 0
    sell_n = (by_side.get("SELL") or {}).get("n") or 0
    if buy_n < MIN_N and sell_n < MIN_N:
        usefulness = "insufficient_evidence"
    elif buy == "POS" and sell == "POS":
        usefulness = "universally_useful"
    elif buy == "POS" and sell != "POS":
        usefulness = "primarily_useful_on_BUY"
    elif sell == "POS" and buy != "POS":
        usefulness = "primarily_useful_on_SELL"
    else:
        usefulness = "insufficient_evidence"
    sess_signs = [v.get("sign") for v in by_sess.values() if not v.get("small_n")]
    hour_signs = [v.get("sign") for v in by_hour.values() if not v.get("small_n")]
    session_dependent = bool(sess_signs) and ("POS" in sess_signs and "NEG" in sess_signs)
    time_dependent = bool(hour_signs) and ("POS" in hour_signs and "NEG" in hour_signs)
    if usefulness.startswith("primarily") or usefulness == "universally_useful":
        pass
    elif session_dependent:
        usefulness = "session_dependent"
    elif time_dependent:
        usefulness = "time_dependent"
    return {
        "usefulness": usefulness,
        "session_dependent": session_dependent,
        "time_dependent": time_dependent,
        "side_specific_parameters": False,
        "session_specific_parameters": False,
    }


def run_phase87_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p83 = _safe_load_json(root / PHASE83_JSON) or {}
    p86 = _safe_load_json(root / PHASE86_JSON) or {}
    walks = p83.get("walks") or {}
    survivors = p86.get("survivors") or []
    names = list(survivors) if survivors else list(TESTABLE_FAMILIES)
    if p83.get("hybrid_created") and "HYBRID" not in names and "HYBRID" in (p83.get("walks") or {}):
        if not survivors:
            pass
    by_family = {}
    for name in names:
        w = walks.get(name) or []
        if not w:
            by_family[name] = {"name": name, "usefulness": "insufficient_evidence"}
            continue
        by_side = _group_delta(w, "side")
        by_sess = _group_delta(w, "sess")
        by_hour = _group_delta(w, "hour")
        by_year = _group_delta(w, "year")
        inter = classify_interaction(by_side, by_sess, by_hour)
        by_family[name] = {
            "name": name,
            "analyzed_as_survivor": name in survivors,
            "by_side": by_side,
            "by_session": by_sess,
            "by_hour_utc": by_hour,
            "by_year": by_year,
            **inter,
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
        "survivors": survivors,
        "analyzed_families": names,
        "by_family": by_family,
        "no_side_specific_parameters": True,
        "no_session_specific_parameters": True,
        "hypotheses": [
            {
                "id": "H87-01",
                "claim": "Protection usefulness can be diagnosed by existing side/session/hour labels without new parameters.",
                "result": {k: v.get("usefulness") for k, v in by_family.items()},
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": names,
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
        "artifacts": {"json": PHASE87_JSON, "md": PHASE87_MD},
    }
    (root / PHASE87_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE87_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 87 — Profit-Protection Interactions",
        "",
        "Diagnosis only. No side-specific or session-specific parameters. Not optimal.",
        f"Survivors from Phase 86: `{survivors}`. Analyzed: `{names}`.",
        "",
    ]
    for name, row in by_family.items():
        lines.append(
            f"- `{name}`: usefulness=`{row.get('usefulness')}` "
            f"BUY=`{((row.get('by_side') or {}).get('BUY') or {}).get('sign')}` "
            f"SELL=`{((row.get('by_side') or {}).get('SELL') or {}).get('sign')}` "
            f"session_dependent=`{row.get('session_dependent')}` time_dependent=`{row.get('time_dependent')}`"
        )
    (root / PHASE87_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase87_collection(Path("."))
    print({k: v.get("usefulness") for k, v in p["by_family"].items()})
