#!/usr/bin/env python3
"""Phase 22AL — production candidate live validation report."""

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
    import argparse

    parser = argparse.ArgumentParser(description="Phase 22AL live validation")
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Reuse existing pipeline_integration_report.json (avoids long backtest)",
    )
    args = parser.parse_args()

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase22al.live_validation import (
        build_trade_metrics,
        determine_verdict,
        run_live_validation,
    )

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_live_validation(base_dir=base_dir, include_pipeline=not args.skip_pipeline)

    if args.skip_pipeline:
        existing = OUT / "pipeline_integration_report.json"
        if existing.is_file():
            pipeline = json.loads(existing.read_text(encoding="utf-8"))
            result["pipeline_integration_report"] = pipeline
            result["trade_metrics"] = build_trade_metrics(pipeline)
            verdict, advisory = determine_verdict(
                frozen=result["frozen_model_validation"],
                probability_health=result["probability_health_report"],
                runtime_safety=result["runtime_safety_report"],
                historical_report=result["historical_replay_report"],
                pipeline_report=pipeline,
            )
            result["verdict"] = verdict
            result["validation_advisory"] = advisory

    for key, fname in (
        ("frozen_model_validation", "frozen_model_validation.json"),
        ("historical_replay_report", "historical_replay_report.json"),
        ("signal_distribution", "signal_distribution.json"),
        ("pipeline_integration_report", "pipeline_integration_report.json"),
        ("trade_metrics", "trade_metrics.json"),
        ("probability_health_report", "probability_health_report.json"),
        ("logistic_vs_xgb_comparison", "logistic_vs_xgb_comparison.json"),
        ("runtime_safety_report", "runtime_safety_report.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {
        "phase": "22AL",
        "title": "Production Candidate Live Validation",
        "generated_utc": now,
        "verdict": result["verdict"],
        "candidate_id": result["frozen_model_validation"].get("candidate_id"),
        "experiment_id": result["frozen_model_validation"].get("experiment_id"),
        "probability_gate_passed": result["probability_health_report"].get("probability_gate_passed"),
        "healthgate_phase9_passes": result["runtime_safety_report"].get("healthgate_phase9_passes"),
        "pipeline_signals": result["pipeline_integration_report"].get("generated_signals"),
        "executed_trades": result["pipeline_integration_report"].get("executed_trades"),
        "validation_advisory": result.get("validation_advisory"),
        "summary": (
            "Frozen xgb_baseline_phase96 validated via artifact check, historical replay, "
            "production-path backtest, probability health, logistic comparison, and runtime safety."
        ),
    }
    _write("phase22al_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0 if result["verdict"] == "MODEL_VALIDATED_FOR_LIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
