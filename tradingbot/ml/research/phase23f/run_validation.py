#!/usr/bin/env python3
"""Phase 23F — shadow validation runner."""

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
    from tradingbot.ml.research.phase23f.shadow_validation import run_shadow_validation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_shadow_validation(base_dir=base_dir)

    for key, fname in (
        ("pipeline_a_results", "pipeline_a_results.json"),
        ("pipeline_b_results", "pipeline_b_results.json"),
        ("parallel_comparison", "parallel_comparison.json"),
        ("window_validation", "window_validation.json"),
        ("walkforward_validation", "walkforward_validation.json"),
        ("monte_carlo_validation", "monte_carlo_validation.json"),
        ("bootstrap_validation", "bootstrap_validation.json"),
        ("regime_validation", "regime_validation.json"),
        ("runtime_safety", "runtime_safety.json"),
        ("deployment_recommendation", "deployment_recommendation.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    dep = result["deployment_recommendation"]
    final = {
        "phase": "23F",
        "title": "Pre-Production Filter Integration Validation (Shadow)",
        "generated_utc": now,
        "verdict": result["verdict"],
        "approve_deploy": dep["checks"].get("approve_deploy"),
        "window_b_wins": dep["checks"].get("window_b_wins_pf_count"),
        "walkforward_b_stable": dep["checks"].get("walkforward_b_stable"),
        "montecarlo_b_passed": dep["checks"].get("montecarlo_b_passed"),
        "summary": dep.get("recommendation"),
    }
    _write("phase23f_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
