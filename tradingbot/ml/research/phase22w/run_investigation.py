#!/usr/bin/env python3
"""Phase 22W — training criterion root-cause verification."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase22w.selection_audit import run_verification

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22W selection criterion audit...", flush=True)
    result = run_verification(base_dir=base_dir)

    for key in (
        "model_selection_pipeline",
        "candidate_ranking",
        "candidate_probability_analysis",
        "selection_criteria_audit",
        "first_engineering_mistake",
    ):
        payload = {**result[key], "generated_utc": now}
        fname = {
            "model_selection_pipeline": "model_selection_pipeline.json",
            "candidate_ranking": "candidate_ranking.json",
            "candidate_probability_analysis": "candidate_probability_analysis.json",
            "selection_criteria_audit": "selection_criteria_audit.json",
            "first_engineering_mistake": "first_engineering_mistake.json",
        }[key]
        _write(fname, payload)

    final = {
        "phase": "22W",
        "title": "Training Criterion Root-Cause Verification",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "first_engineering_mistake": result["first_engineering_mistake"]["answer"],
        "summary": result["first_engineering_mistake"]["why_this_survives_as_primary"],
        "winner": result["candidate_ranking"].get("winner", {}).get("experiment_id"),
        "winner_pf": result["candidate_ranking"].get("winner", {}).get("mean_profit_factor"),
        "winner_composite": result["candidate_ranking"].get("winner", {}).get("composite_score"),
        "probability_gates_in_selection": False,
        "frozen_winner_buy_zone_22u": "0%",
        "frozen_winner_max_p_22u": 0.434012,
    }
    _write("phase22w_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
