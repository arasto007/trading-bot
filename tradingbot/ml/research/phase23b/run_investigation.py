#!/usr/bin/env python3
"""Phase 23B — feature pipeline repair validation report."""

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
    from tradingbot.ml.research.phase23b.repair_validation import run_repair_validation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_repair_validation(base_dir=base_dir)

    for key, fname in (
        ("feature_mapping_patch", "feature_mapping_patch.json"),
        ("runtime_feature_validation", "runtime_feature_validation.json"),
        ("adapter_validation", "adapter_validation.json"),
        ("featurebuilder_trace", "featurebuilder_trace.json"),
        ("predict_proba_validation", "predict_proba_validation.json"),
        ("runtime_before_after", "runtime_before_after.json"),
        ("regression_report", "regression_report.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {
        "phase": "23B",
        "title": "Feature Pipeline Repair (Safe Hotfix)",
        "generated_utc": now,
        "verdict": result["verdict"],
        "predict_proba_called": result["predict_proba_validation"].get("predict_proba_called"),
        "feature_source": result["featurebuilder_trace"]["runtime_sample"].get("feature_source"),
        "model_pass_proxy": result["runtime_feature_validation"]["range_batch"].get("model_pass_proxy"),
        "freeze_artifacts_unchanged": result["regression_report"]["unchanged"].get("freeze_artifacts"),
        "summary": (
            "Runtime Phase 9.9 inference now uses FeatureBuilder via KernelAdapter candle wiring. "
            "PHASE99_FEATURE_MAP completed, silent phase99 zero-fill removed, validation added before predict_proba."
        ),
    }
    _write("phase23b_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0 if result["verdict"] == "FEATURE_PIPELINE_REPAIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
