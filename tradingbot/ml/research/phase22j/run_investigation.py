#!/usr/bin/env python3
"""Phase 22J — engine-level signal investigation (research-only)."""

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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="A")
    parser.add_argument("--profile-stride", type=int, default=10)
    parser.add_argument("--skip-backtests", action="store_true")
    args = parser.parse_args()

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase22f.config import build_dataset
    from tradingbot.ml.research.phase22j.engine_candidates import list_engine_candidates, top_five_engine_candidates
    from tradingbot.ml.research.phase22j.range_forensics import profile_range_engine
    from tradingbot.ml.research.phase22j.runner import run_engine_candidate
    from tradingbot.ml.research.phase22j.selection import compare_engine_candidates, recommend_engine_fix
    from tradingbot.ml.research.phase22j.training_alignment import validate_training_alignment
    from tradingbot.ml.research.phase22j.trend_forensics import profile_trend_engine

    t0 = time.perf_counter()
    dataset = build_dataset(args.dataset)
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print(f"Phase 22J | dataset={args.dataset} | output={OUT}", flush=True)

    print("  range forensics...", flush=True)
    range_f = await profile_range_engine(dataset, stride=args.profile_stride)
    _write("range_engine_forensics.json", range_f)

    print("  trend forensics...", flush=True)
    trend_f = await profile_trend_engine(dataset, stride=args.profile_stride)
    _write("trend_engine_forensics.json", trend_f)

    alignment = validate_training_alignment(base_dir=base_dir)
    _write("training_alignment_validation.json", alignment)

    results: list[dict] = []
    if not args.skip_backtests:
        run_list = [c for c in list_engine_candidates() if c.id == "22J-BASELINE"] + top_five_engine_candidates()
        for i, cand in enumerate(run_list):
            print(f"  engine backtest {i + 1}/{len(run_list)}: {cand.id}...", flush=True)
            try:
                results.append(await run_engine_candidate(dataset, cand, base_dir=base_dir))
            except Exception as exc:
                results.append({"candidate_id": cand.id, "title": cand.title, "error": str(exc)})

    _write("datasetA_engine_results.json", {"phase": "22J", "dataset": dataset.to_dict(), "results": results})

    comparison = compare_engine_candidates(results) if results else {"ranked": []}
    _write("engine_candidate_comparison.json", comparison)

    rec = recommend_engine_fix(comparison, range_f, trend_f)
    _write("recommended_engine_fix.json", rec)

    aligned = alignment.get("aligned", False)
    range_primary = (range_f.get("root_cause_hypothesis") or {}).get("primary")
    pf_improved = any(
        float(r.get("pf_delta") or 0) > 0
        for r in comparison.get("ranked", [])
        if r.get("candidate_id") != "22J-BASELINE"
    )
    verdict = (
        "READY_FOR_ENGINE_IMPLEMENTATION"
        if rec.get("selected_id") and rec.get("selected_id") != "22J-BASELINE" and aligned
        else "ENGINE_REQUIRES_FURTHER_FORENSICS"
    )

    final = {
        "phase": "22J",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "production_modified": False,
        "dataset": dataset.to_dict(),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "verdict": verdict,
        "final_questions": {
            "1_true_engine_bottleneck": rec.get("true_engine_bottleneck"),
            "2_problem_category": rec.get("problem_category"),
            "3_highest_roi_modification": rec.get("selected_id"),
            "4_expected_pf_improvement": rec.get("predicted_impact", {}).get("profit_factor_improvement"),
            "5_engineering_risk": rec.get("predicted_impact", {}).get("engineering_risk"),
        },
        "range_primary_cause": range_primary,
        "trend_bottleneck": trend_f.get("bottleneck"),
        "training_aligned": aligned,
        "pf_improved_any_candidate": pf_improved,
        "recommended": rec,
    }
    _write("phase22j_final_report.json", final)

    print(f"\nPhase 22J complete | verdict={verdict} | {final['elapsed_sec']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
