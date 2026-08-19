#!/usr/bin/env python3
"""Phase 23E — RANGE filter recalibration study runner."""

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
    from tradingbot.ml.research.phase23e.range_filter_study import run_study

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_study(base_dir=base_dir)

    for key, fname in (
        ("grid_search_results", "grid_search_results.json"),
        ("walkforward_results", "walkforward_results.json"),
        ("monte_carlo_results", "monte_carlo_results.json"),
        ("statistical_validation", "statistical_validation.json"),
        ("regime_validation", "regime_validation.json"),
        ("safety_analysis", "safety_analysis.json"),
        ("winner_profile", "winner_profile.json"),
        ("production_recommendation", "production_recommendation.json"),
        ("repair_plan", "repair_plan.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {
        "phase": "23E",
        "title": "RANGE Filter Recalibration (Scientific Study)",
        "generated_utc": now,
        "verdict": result["verdict"],
        "profiles_evaluated": result["search_space"]["total_profiles"],
        "range_cohort_size": result["grid_search_results"]["records_total"],
        "winner_profile_id": result["winner_profile"].get("winner_profile", {}).get("profile_id"),
        "strict_criteria_pass": result["winner_profile"].get("strict_criteria_pass"),
        "statistically_significant": result["statistical_validation"].get("statistically_significant_improvement"),
        "summary": result["production_recommendation"].get("rationale"),
    }
    _write("phase23e_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
