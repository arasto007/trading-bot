#!/usr/bin/env python3
"""Phase 22V — phase9_9 training pipeline forensics."""

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
    from tradingbot.ml.research.phase22v.model_audit import run_forensics

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running phase9_9 training pipeline forensics...", flush=True)
    result = run_forensics(base_dir=base_dir)
    if result.get("error"):
        print(json.dumps(result, indent=2))
        return 1

    pipeline = {**result["training_pipeline_map"], "generated_utc": now}
    weights = {**result["model_weights"], "generated_utc": now, "phase": "22V"}
    feat_stats = {**result["feature_statistics"], "generated_utc": now, "phase": "22V"}
    predictiveness = {**result["feature_predictiveness"], "generated_utc": now, "phase": "22V"}
    process = {**result["training_process"], "generated_utc": now, "phase": "22V"}
    convergence = {**result["convergence_report"], "generated_utc": now, "phase": "22V"}
    train_probs = {**result["training_probability_distribution"], "generated_utc": now, "phase": "22V"}
    labels = {**result["training_label_distribution"], "generated_utc": now, "phase": "22V"}

    histogram = {
        "phase": "22V",
        "generated_utc": now,
        "freeze_train_slice": result["probability_histogram_train_slice"],
        "full_resolved_dataset_v2": result["probability_histogram_full_dataset"],
    }

    root_cause = {
        "phase": "22V",
        "generated_utc": now,
        "verdict": result["verdict"],
        "root_causes": result["root_causes"],
        "narrative": result["root_cause_narrative"],
        "logistic_suitability": result["logistic_suitability"],
    }

    final = {
        "phase": "22V",
        "title": "Phase9_9 Training Pipeline Forensics",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "root_causes": result["root_causes"],
        "summary": result["root_cause_narrative"],
        "freeze_train_rows": result["feature_statistics"]["train_rows"],
        "training_buy_zone_pct": result["training_probability_distribution"]["freeze_train_slice"]["buy_zone_pct"],
        "training_max_p_win": result["training_probability_distribution"]["freeze_train_slice"]["max_p_win"],
        "structure_distance_zero_pct": result["feature_statistics"]["before_scaling"].get(
            "structure_distance", {}
        ).get("zero_pct"),
        "label_positive_pct": result["training_label_distribution"]["positive_pct"],
        "converged": result["convergence_report"].get("converged"),
    }

    _write("training_pipeline_map.json", pipeline)
    _write("feature_statistics.json", feat_stats)
    _write("feature_predictiveness.json", predictiveness)
    _write("training_process.json", process)
    _write("convergence_report.json", convergence)
    _write("training_probability_distribution.json", train_probs)
    _write("training_label_distribution.json", labels)
    _write("probability_histogram.json", histogram)
    _write("model_weights.json", weights)
    _write("root_cause_report.json", root_cause)
    _write("phase22v_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"], "causes": result["root_causes"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
