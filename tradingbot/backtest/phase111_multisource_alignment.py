"""Phase 111 — multi-source causal alignment.

Combinations are declared only from sources that exist and passed causal-validity.
No brute-force feature search.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase107_tick_intrabar_research import PHASE107_JSON
from tradingbot.backtest.phase108_spread_path_research import PHASE108_JSON
from tradingbot.backtest.phase109_htf_context_research import PHASE109_JSON
from tradingbot.backtest.phase110_news_context_research import PHASE110_JSON

PHASE = "111"
PHASE111_JSON = "logs/phase111_multisource_alignment.json"
PHASE111_MD = "docs/PHASE111_MULTISOURCE_ALIGNMENT.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "n_declared",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _causal_ok(status: str | None) -> bool:
    return status in {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE", "DATA_LIMITED"}


def declare_combinations(tick: str, spread: str, htf: str, news: str) -> list[dict[str, Any]]:
    """Declare before evaluation. Only independently justified pairs."""
    tick_ok = _causal_ok(tick) and tick != "DATA_MISSING"
    spread_ok = _causal_ok(spread) and spread != "DATA_MISSING"
    htf_ok = _causal_ok(htf) and htf != "DATA_MISSING"
    news_ok = _causal_ok(news) and news != "DATA_MISSING"
    fams = []
    # A tick+spread
    if tick_ok and spread_ok:
        fams.append(
            {
                "name": "A_TICK_SPREAD",
                "why": "Same-timestamp microstructure: directional ticks and contemporaneous spread.",
                "sources": ["tick", "spread"],
            }
        )
    # B tick+HTF
    if tick_ok and htf_ok:
        fams.append(
            {
                "name": "B_TICK_HTF",
                "why": "Intrabar path inside an HTF directional context.",
                "sources": ["tick", "htf"],
            }
        )
    # C spread+HTF
    if spread_ok and htf_ok:
        fams.append(
            {
                "name": "C_SPREAD_HTF",
                "why": "HTF bias with observed spread state at the same event time.",
                "sources": ["spread", "htf"],
            }
        )
    # D HTF+news
    if htf_ok and news_ok:
        fams.append(
            {
                "name": "D_HTF_NEWS",
                "why": "HTF context near a scheduled event, without using the news outcome.",
                "sources": ["htf", "news"],
            }
        )
    # E tick+spread+HTF
    if tick_ok and spread_ok and htf_ok:
        fams.append(
            {
                "name": "E_TICK_SPREAD_HTF",
                "why": "Full microstructure plus HTF context, only if each source is independently aligned.",
                "sources": ["tick", "spread", "htf"],
            }
        )
    return fams


def run_phase111_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p107 = _safe_load_json(root / PHASE107_JSON) or {}
    p108 = _safe_load_json(root / PHASE108_JSON) or {}
    p109 = _safe_load_json(root / PHASE109_JSON) or {}
    p110 = _safe_load_json(root / PHASE110_JSON) or {}
    tick = p107.get("TICK_DISCRIMINATOR_STATUS")
    spread = p108.get("SPREAD_DISCRIMINATOR_STATUS")
    htf = p109.get("HTF_DISCRIMINATOR_STATUS")
    news = p110.get("NEWS_DISCRIMINATOR_STATUS")
    declared = declare_combinations(tick, spread, htf, news)
    # DATA_MISSING sources are not causally valid for the event tape.
    evals = {}
    for fam in declared:
        evals[fam["name"]] = {
            "declared_before_eval": True,
            "status": "NOT_EVALUATED_NO_JOINT_COVERAGE",
            "reason": "Combination declared but joint event coverage was not fabricated.",
            "kind": "COUNTERFACTUAL",
        }
    status = "DATA_MISSING" if not declared else "INSUFFICIENT_EVIDENCE"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "brute_force_combinations": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "source_status": {"tick": tick, "spread": spread, "htf": htf, "news": news},
        "declared_before_evaluation": True,
        "n_declared": len(declared),
        "families": declared,
        "counterfactuals": evals,
        "MULTISOURCE_DISCRIMINATOR_STATUS": status,
        "evidence_kind": "INFERENCE",
        "hypotheses": [
            {
                "id": "H111-01",
                "claim": "A causally justified combination of non-OHLC sources separates C/D from E/F.",
                "result": status,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["declare_combinations"],
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
        "artifacts": {"json": PHASE111_JSON, "md": PHASE111_MD},
    }
    (root / PHASE111_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE111_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE111_MD).write_text(
        "\n".join(
            [
                "# Phase 111 — Multi-Source Causal Alignment",
                "",
                "INFERENCE. Combinations declared only if each source is causally valid on the event tape.",
                f"**MULTISOURCE_DISCRIMINATOR_STATUS:** `{status}`",
                f"**n_declared:** `{len(declared)}`",
                f"Source statuses: tick=`{tick}` spread=`{spread}` htf=`{htf}` news=`{news}`",
                "No brute-force combinations. DATA_MISSING sources were not paired.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase111_collection(Path("."))
    print(p["n_declared"], p["MULTISOURCE_DISCRIMINATOR_STATUS"])
