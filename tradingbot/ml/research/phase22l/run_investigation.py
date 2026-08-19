#!/usr/bin/env python3
"""Phase 22L — dataset refresh and feature pipeline repair (research only)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


def _verdict(refresh: dict, coverage: dict, comparison: dict, range_old: dict, range_new: dict) -> dict:
    merge_delta = coverage.get("merge_hit_delta_pct", 0)
    measurable = comparison.get("measurable_change", False)
    pwin_std_old = range_old.get("probability_stats", {}).get("std", 0)
    structure_flat = "structure_distance" in range_new.get("flat_features", [])

    if merge_delta > 5 and measurable:
        code = "A"
        label = "Dataset refresh solved feature problem"
    elif abs(merge_delta) < 1 and not measurable and structure_flat:
        code = "B"
        label = "Dataset refresh had no measurable effect"
    elif merge_delta > 0 and not measurable:
        code = "C"
        label = "Feature pipeline still corrupt"
    else:
        code = "D"
        label = "Range model itself is defective"

    # Refine: sparse merge + flat structure → D not C
    if code == "C" and structure_flat and pwin_std_old < 0.01:
        code = "D"
        label = "Range model itself is defective"

    return {
        "phase": "22L",
        "verdict_code": code,
        "verdict_label": label,
        "evidence": {
            "merge_hit_delta_pct": merge_delta,
            "measurable_engine_change": measurable,
            "structure_distance_flat": structure_flat,
            "p_win_std_old": pwin_std_old,
            "refresh_row_delta": refresh.get("delta", {}).get("row_delta"),
        },
        "primary_problem_was_dataset_staleness": code == "A",
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-rebuild", action="store_true", help="Use existing artifacts if present")
    args = parser.parse_args()

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase22l.audit_pipeline import audit_dataset_generation_pipeline
    from tradingbot.ml.research.phase22l.comparison import compare_before_after
    from tradingbot.ml.research.phase22l.coverage import audit_feature_coverage
    from tradingbot.ml.research.phase22l.range_quality import audit_range_input_quality
    from tradingbot.ml.research.phase22l.rebuild import (
        OLD_SNAPSHOT,
        REFRESHED,
        load_old_snapshot,
        load_refreshed_dataset,
        rebuild_dataset_v2_research,
        snapshot_old_dataset,
    )
    from tradingbot.ml.research.phase22l.unified_audit import audit_unified_frame
    from tradingbot.ml.research.phase22f.config import build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset

    t0 = time.perf_counter()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print(f"Phase 22L | output={OUT}", flush=True)

    print("  step 1 — audit pipeline...", flush=True)
    pipeline = audit_dataset_generation_pipeline(base_dir=base_dir)
    _write("dataset_generation_pipeline.json", pipeline)

    print("  step 2 — rebuild dataset (research artifact)...", flush=True)
    if args.skip_rebuild and REFRESHED.is_file() and OLD_SNAPSHOT.is_file():
        old = load_old_snapshot()
        new = load_refreshed_dataset()
        refresh = {
            "phase": "22L",
            "step": 2,
            "status": "skipped_reused_artifact",
            "production_unmodified": True,
            "output_path": str(REFRESHED),
            "old_snapshot_path": str(OLD_SNAPSHOT),
            "old_dataset": {"rows": len(old), "max_timestamp": str(old["timestamp"].max())},
            "new_dataset": {"rows": len(new), "max_timestamp": str(new["timestamp"].max())},
            "delta": {
                "row_delta": len(new) - len(old),
                "max_timestamp_extended": str(new["timestamp"].max()) != str(old["timestamp"].max()),
            },
        }
    else:
        refresh = rebuild_dataset_v2_research(base_dir=base_dir)
    _write("dataset_refresh_report.json", refresh)
    if refresh.get("status") == "fail":
        print("  rebuild failed", refresh, flush=True)
        return 1

    old_ds = load_old_snapshot()
    new_ds = load_refreshed_dataset()

    print("  step 3 — coverage audit...", flush=True)
    coverage = await audit_feature_coverage(old_dataset=old_ds, new_dataset=new_ds)
    _write("feature_coverage_after_refresh.json", coverage)

    configure_research_env()
    candles = await load_ohlcv_for_dataset(build_dataset("A"), "M5")

    print("  step 4 — unified frame audit...", flush=True)
    unified = audit_unified_frame(candles, old_ds, new_ds)
    _write("unified_frame_audit.json", unified)

    print("  step 5 — range input quality...", flush=True)
    range_old = audit_range_input_quality(candles, old_ds)
    range_new = audit_range_input_quality(candles, new_ds)
    range_report = {"phase": "22L", "step": 5, "old_dataset": range_old, "refreshed_dataset": range_new}
    _write("range_input_quality.json", range_report)

    print("  step 6 — before/after comparison...", flush=True)
    comparison = await compare_before_after(old_ds, new_ds)
    _write("before_after_comparison.json", comparison)

    verdict = _verdict(refresh, coverage, comparison, range_old, range_new)
    _write("root_cause_verdict.json", verdict)

    final = {
        "phase": "22L",
        "title": "Dataset Refresh & Feature Pipeline Repair",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "production_modified": False,
        "constraints_honored": True,
        "verdict": verdict["verdict_code"],
        "verdict_label": verdict["verdict_label"],
        "was_dataset_the_main_problem": verdict["primary_problem_was_dataset_staleness"],
        "summary": (
            "Rebuilt dataset_v2 to research artifact using SparseEventDatasetBuilder + v2 gate. "
            "Compared merge coverage and range engine outputs on Dataset A with old vs refreshed dataset. "
            "No engine, threshold, or production file changes."
        ),
        "reports": [
            "dataset_generation_pipeline.json",
            "dataset_refresh_report.json",
            "feature_coverage_after_refresh.json",
            "unified_frame_audit.json",
            "range_input_quality.json",
            "before_after_comparison.json",
            "root_cause_verdict.json",
            "phase22l_final_report.json",
        ],
    }
    _write("phase22l_final_report.json", final)
    print(f"Phase 22L complete | verdict={verdict['verdict_code']} | {final['elapsed_sec']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
