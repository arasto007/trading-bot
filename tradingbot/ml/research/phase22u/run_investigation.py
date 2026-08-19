#!/usr/bin/env python3
"""Phase 22U — phase9_9 model capability verification."""

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
    from tradingbot.ml.research.phase22u.model_audit import run_capability_audit

    now = datetime.now(timezone.utc).isoformat()
    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(legacy.get("BASE_DIR"))

    print("Running phase9_9 capability audit on full dataset_v2...", flush=True)
    audit = run_capability_audit(base_dir=base_dir)
    if audit.get("error"):
        print(json.dumps(audit, indent=2))
        return 1

    audit["generated_utc"] = now

    weights = {**audit["model_weights"], "generated_utc": now, "phase": "22U"}
    train_probs = {**audit["training_probability_distribution"], "generated_utc": now, "phase": "22U"}
    train_labels = {**audit["training_label_distribution"], "generated_utc": now, "phase": "22U"}
    histogram = {**audit["probability_histogram"], "generated_utc": now, "phase": "22U"}

    capability = {
        "phase": "22U",
        "generated_utc": now,
        "can_produce_buy_on_training": audit["training_probability_distribution"]["can_produce_buy_on_training"],
        "mostly_p_win_below_0_45": audit["training_probability_distribution"]["mostly_below_0_45"],
        "training_zones": audit["training_probability_distribution"]["zones"],
        "training_statistics": audit["training_probability_distribution"]["statistics"],
        "dataset_a_zones": audit.get("dataset_a_subset", {}).get("zones"),
        "dataset_a_statistics": audit.get("dataset_a_subset", {}).get("statistics"),
        "model_type": audit["model_weights"].get("model_type"),
        "feature_importance": audit["model_weights"].get("feature_importance_abs_coef_normalized"),
    }

    final = {
        "phase": "22U",
        "title": "Model Capability Verification (phase9_9)",
        "generated_utc": now,
        "production_modified": False,
        "method": audit["method"],
        "verdict": audit["verdict"],
        "verdict_reason": audit["verdict_reason"],
        "training_rows_scored": audit["training_probability_distribution"]["rows_scored"],
        "training_zones": audit["training_probability_distribution"]["zones"],
        "training_label_positive_pct": audit["training_label_distribution"]["positive_pct"],
        "training_p_win_mean": audit["training_probability_distribution"]["statistics"].get("mean"),
        "training_p_win_std": audit["training_probability_distribution"]["statistics"].get("std"),
        "dataset_a_rows": audit.get("dataset_a_subset", {}).get("rows_in_dataset_v2"),
        "dataset_a_buy_zone_pct": (audit.get("dataset_a_subset") or {}).get("zones", {}) or {},
        "summary": (
            f"Verdict={audit['verdict']}. "
            f"Training buy_zone={audit['training_probability_distribution']['zones']['buy_zone_pct']}% "
            f"sell_zone={audit['training_probability_distribution']['zones']['sell_zone_pct']}% "
            f"neutral={audit['training_probability_distribution']['zones']['neutral_pct']}% "
            f"P(win) mean={audit['training_probability_distribution']['statistics'].get('mean')} "
            f"std={audit['training_probability_distribution']['statistics'].get('std')}. "
            f"Labels positive={audit['training_label_distribution']['positive_pct']}%."
        ),
    }

    _write("model_weights.json", weights)
    _write("training_probability_distribution.json", train_probs)
    _write("training_label_distribution.json", train_labels)
    _write("probability_histogram.json", histogram)
    _write("model_capability_report.json", capability)
    _write("phase22u_final_report.json", final)

    print(json.dumps({"verdict": audit["verdict"], "zones": audit["training_probability_distribution"]["zones"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
