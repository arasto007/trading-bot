#!/usr/bin/env python3
"""Phase 51 — Profitability proximity assessment."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(name: str) -> dict:
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def run_phase51() -> dict:
    from tradingbot.ml.research.phase51.profitability_score import profitability_proximity

    r50 = _load("phase50_final_report.json")
    r49 = _load("phase49_final_report.json")
    r34a = _load("phase34a_final_report.json")
    r35 = _load("phase35_final_report.json")

    raw_pf = (r34a.get("raw_ml_statistics") or {}).get("profit_factor", 1.15)
    exec_pf = (r34a.get("executed_statistics") or {}).get("profit_factor", 0.31)

    prox = profitability_proximity(
        strict_gate_passed=bool(r50.get("gate_passed")),
        mean_pf=float(r50.get("mean_pf", 0) or 0),
        mean_auc=float(r50.get("mean_auc", 0) or 0),
        windows_count=len(r50.get("walk_forward_windows") or []),
        windows_pf_above_1_3=int(r50.get("windows_pf_above_1_3", 0) or 0),
        raw_ml_pf=float(raw_pf),
        executed_pf=float(exec_pf),
        label_prod_match_pct=float(r35.get("stored_vs_production_match_pct", 70.38)),
        v7_rows=int(r49.get("dataset_v7_rows", 0) or 0),
    )

    gate = "BLOCK_PRODUCTION_INTEGRATION"
    if r50.get("gate_passed"):
        gate = "INTEGRATION_REVIEW_ELIGIBLE"
    elif prox["proximity_score"] >= 60:
        gate = "CONTINUE_RESEARCH_HIGH_PRIORITY"

    return {
        "now": NOW,
        "verdict": prox["proximity_band"],
        "integration_gate": gate,
        "proximity": prox,
        "strict_gate": {
            "passed": r50.get("gate_passed"),
            "verdict": r50.get("verdict"),
            "mean_pf": r50.get("mean_pf"),
            "mean_auc": r50.get("mean_auc"),
        },
        "how_close_to_profitable_robot": {
            "score_0_100": prox["proximity_score"],
            "band": prox["proximity_band"],
            "deploy_blocked": not bool(r50.get("gate_passed")),
            "summary_fa": _summary_fa(prox, r50, exec_pf),
        },
    }


def _summary_fa(prox: dict, r50: dict, exec_pf: float) -> str:
    score = prox["proximity_score"]
    if r50.get("gate_passed"):
        return (
            f"حدود {score:.0f}% نزدیک روبات سودده — gate سخت گذرانده شد؛ "
            "مرحله بعد shadow/paper trading است نه live."
        )
    if score >= 50:
        return (
            f"حدود {score:.0f}% نزدیک — ML در حال بهبود اما مسیر اجرا (exec PF={exec_pf}) "
            "هنوز سودده نیست."
        )
    return (
        f"حدود {score:.0f}% نزدیک — هنوز در پژوهش میانی؛ "
        "چند سال walk-forward و capture سیگنال کامل لازم است."
    )


def main() -> None:
    data = run_phase51()
    (ROOT / "phase51_final_report.json").write_text(
        json.dumps({"phase": "51", "title": "Profitability Proximity", **data}, indent=2, default=str),
        encoding="utf-8",
    )
    (ROOT / "profitability_proximity.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    status = {
        "updated_utc": NOW,
        "status": "PHASE_51_COMPLETE",
        "engineering_verdict": data["integration_gate"],
        "proximity_score": data["proximity"]["proximity_score"],
        "proximity_band": data["verdict"],
        "strict_gate_passed": data["strict_gate"].get("passed"),
        "how_close_pct": data["how_close_to_profitable_robot"]["score_0_100"],
        "next_step": data["proximity"]["interpretation"],
    }
    (ROOT / "ENGINEERING_STATUS.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  wrote phase51_final_report.json", flush=True)
    print("  wrote ENGINEERING_STATUS.json", flush=True)
    print(json.dumps(data["how_close_to_profitable_robot"], indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
