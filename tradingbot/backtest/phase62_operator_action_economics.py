"""Phase 62 — operator / technical action economics.

RESEARCH ONLY. Qualitative ranking. No fake probabilities. No trading.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "62"
PHASE62_JSON = "logs/phase62_operator_action_economics.json"
PHASE62_MD = "docs/PHASE62_OPERATOR_ACTION_ECONOMICS.md"
PHASE57_JSON = "logs/phase57_account_product_forensics.json"
PHASE61_JSON = "logs/phase61_edge_survival_forensics.json"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "actions",
    "ranking",
    "HIGHEST_VALUE_OPERATOR_ACTION",
    "HIGHEST_VALUE_TECHNICAL_ACTION",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def rank_actions(p61: dict[str, Any], p57: dict[str, Any]) -> dict[str, Any]:
    quality = p61.get("EDGE_QUALITY") or UNKNOWN
    decision = (p61.get("decision_economics") or {}).get("answer") or p61.get("DECISION_ECONOMICS")
    fragile = quality in {"FRAGILE", "WEAK"}
    actions = [
        {
            "id": "A",
            "name": "Get Cabinet account product screenshot",
            "INFORMATION_VALUE": "MEDIUM" if fragile else "HIGH",
            "COST": "LOW",
            "SAFETY": "HIGH",
            "DEPENDENCY": "Operator access to Cabinet; secrets redacted",
            "DECISION_IMPACT": "MEDIUM" if not fragile else "LOW",
            "why": "Closes G1 if ECN/CLASSIC/CENT is visible. Does not enlarge gross edge. Commission delta (~0.007R vs ~0.020R) cannot rescue modeled spread/slip failure.",
        },
        {
            "id": "B",
            "name": "Ask LiteFinance support about XAUUSD_i vs XAUUSD",
            "INFORMATION_VALUE": "MEDIUM",
            "COST": "LOW",
            "SAFETY": "HIGH",
            "DEPENDENCY": "Support ticket; no credentials",
            "DECISION_IMPACT": "MEDIUM",
            "why": "Closes G3 / EV-EQ-01. Research tape already uses XAUUSD_i. Equivalence does not create edge.",
        },
        {
            "id": "C",
            "name": "Obtain official commission schedule applicability",
            "INFORMATION_VALUE": "LOW" if fragile else "HIGH",
            "COST": "MEDIUM",
            "SAFETY": "HIGH",
            "DEPENDENCY": "G1 product identity first",
            "DECISION_IMPACT": "LOW" if fragile else "HIGH",
            "why": "Follows G1. Historical zeros remain NOT_PROVEN_SCHEDULE. Not the dominant cost vs spread/slip.",
        },
        {
            "id": "D",
            "name": "Obtain historical Bid/Ask covering eval tape",
            "INFORMATION_VALUE": "MEDIUM",
            "COST": "HIGH",
            "SAFETY": "MEDIUM",
            "DEPENDENCY": "Bounded probes only; hang risk",
            "DECISION_IMPACT": "MEDIUM",
            "why": "Would replace MODELED spread. Expensive. Does not fix recent-180d or TRAIN negativity.",
        },
        {
            "id": "E",
            "name": "Build passive request/fill telemetry infrastructure",
            "INFORMATION_VALUE": "MEDIUM",
            "COST": "HIGH",
            "SAFETY": "HIGH",
            "DEPENDENCY": "Must remain unwired to order_send",
            "DECISION_IMPACT": "MEDIUM",
            "why": "Needed for realized slippage later. Zero pairs today. Not justified as the next unit of work while gross edge is FRAGILE.",
        },
        {
            "id": "F",
            "name": "Perform executable cost-aware backtest after prerequisites",
            "INFORMATION_VALUE": "LOW",
            "COST": "HIGH",
            "SAFETY": "HIGH",
            "DEPENDENCY": "G1 PASS AND G2 PASS AND G3 PASS AND edge not FRAGILE",
            "DECISION_IMPACT": "LOW",
            "why": "Prerequisites unmet. Executable validation of a FRAGILE gross edge is premature.",
        },
        {
            "id": "G",
            "name": "Stop this strategy and redirect effort",
            "INFORMATION_VALUE": "MEDIUM" if fragile else "LOW",
            "COST": "LOW",
            "SAFETY": "HIGH",
            "DEPENDENCY": "None. Research decision only — not a live disable.",
            "DECISION_IMPACT": "HIGH" if fragile else "LOW",
            "why": "If EDGE_QUALITY is FRAGILE, further broker forensics has low expected information. Redirecting research effort is the high-value technical move. This does not modify production strategy files.",
        },
        {
            "id": "H",
            "name": "Continue research on strategy edge",
            "INFORMATION_VALUE": "HIGH",
            "COST": "MEDIUM",
            "SAFETY": "HIGH",
            "DEPENDENCY": "Frozen tape only; no parameter search",
            "DECISION_IMPACT": "HIGH",
            "why": "TRAIN negative, 2023–2024 negative, recent 180d negative, OOS positive: the contradiction is inside the strategy tape, not inside Cabinet product identity.",
        },
    ]
    # Rank: information value HIGH first, then low cost, then high safety, then decision impact.
    order_iv = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    order_cost = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    order_safe = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    order_di = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ranked = sorted(
        actions,
        key=lambda a: (order_iv[a["INFORMATION_VALUE"]], order_cost[a["COST"]], order_safe[a["SAFETY"]], order_di[a["DECISION_IMPACT"]], a["id"]),
    )
    ranking = [{"RANK": i + 1, **row} for i, row in enumerate(ranked)]
    operator_ids = {"A", "B", "C"}
    technical_ids = {"D", "E", "F", "G", "H"}
    best_op = next(r for r in ranking if r["id"] in operator_ids)
    best_tech = next(r for r in ranking if r["id"] in technical_ids)
    return {
        "EDGE_QUALITY": quality,
        "DECISION_ECONOMICS": decision,
        "G1": p57.get("G1"),
        "ACCOUNT_PRODUCT_CANDIDATE": p57.get("ACCOUNT_PRODUCT_CANDIDATE"),
        "actions": actions,
        "ranking": ranking,
        "HIGHEST_VALUE_OPERATOR_ACTION": f"{best_op['id']} {best_op['name']}",
        "HIGHEST_VALUE_TECHNICAL_ACTION": f"{best_tech['id']} {best_tech['name']}",
        "numeric_probabilities_used": False,
    }


def run_phase62_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p61 = _safe_load_json(root / PHASE61_JSON) or {}
    p57 = _safe_load_json(root / PHASE57_JSON) or {}
    ranked = rank_actions(p61, p57)
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        **ranked,
        "OPERATOR_ACTION_VALUE": "LOW_FOR_RESCUE / OPTIONAL_CHEAP_CLOSE",
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "OPTIMIZATION": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE62_JSON, "md": PHASE62_MD},
    }
    (root / PHASE62_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE62_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 62 — Operator Action Economics",
        "",
        f"**HIGHEST_VALUE_OPERATOR_ACTION:** `{payload['HIGHEST_VALUE_OPERATOR_ACTION']}`",
        f"**HIGHEST_VALUE_TECHNICAL_ACTION:** `{payload['HIGHEST_VALUE_TECHNICAL_ACTION']}`",
        f"**EDGE_QUALITY input:** `{ranked['EDGE_QUALITY']}`",
        "",
        "Qualitative ranking only. No numeric probabilities.",
        "",
        "| Rank | ID | Action | Info | Cost | Safety | Impact |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in payload["ranking"]:
        lines.append(
            f"| {r['RANK']} | {r['id']} | {r['name']} | {r['INFORMATION_VALUE']} | {r['COST']} | {r['SAFETY']} | {r['DECISION_IMPACT']} |"
        )
    lines.extend(["", "Action G does not modify production files. It is a research-allocation recommendation.", ""])
    (root / PHASE62_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE62_MD).write_text("\n".join(lines), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase62_collection(Path("."))["HIGHEST_VALUE_TECHNICAL_ACTION"])
