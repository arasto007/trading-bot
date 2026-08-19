#!/usr/bin/env python3
"""Phase 22I — decision engine deep optimization (research-only)."""

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
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="A")
    parser.add_argument("--profile-stride", type=int, default=5)
    parser.add_argument("--skip-backtests", action="store_true")
    args = parser.parse_args()

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy
    from tradingbot.ml.research.phase22c.config import load_phase22c_config
    from tradingbot.ml.research.phase22f.config import build_dataset
    from tradingbot.ml.research.phase22i.candidates import list_policy_candidates, top_five_candidates
    from tradingbot.ml.research.phase22i.hold_profiler import profile_decision_holds
    from tradingbot.ml.research.phase22i.runner import run_candidate_dataset_a
    from tradingbot.ml.research.phase22i.selection import compare_candidates, select_recommended

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    dataset = build_dataset(args.dataset)
    base_dir = load_legacy_config().get("BASE_DIR")
    cfg22 = load_phase22c_config()
    policy = DecisionPolicy(
        min_confidence=cfg22.decision_min_confidence if cfg22.enabled else DecisionPolicy().min_confidence,
    )

    print(f"Phase 22I | dataset={args.dataset} | output={OUT}", flush=True)

    print("  hold chain profiling...", flush=True)
    profile = await profile_decision_holds(dataset, stride=args.profile_stride)
    _write("decision_hold_profile.json", profile)

    candidates = list_policy_candidates(policy=policy)
    top5 = top_five_candidates(policy=policy)
    _write("policy_candidates.json", {
        "phase": "22I",
        "policy_threshold": policy.min_confidence,
        "all_candidates": [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "engineering_type": c.engineering_type,
                "threshold_tuning": c.threshold_tuning,
            }
            for c in candidates
        ],
        "top_five_simulated": [c.id for c in top5],
    })

    results: list[dict] = []
    if not args.skip_backtests:
        run_list = [c for c in candidates if c.id == "22I-BASELINE"] + top5
        for idx, cand in enumerate(run_list):
            print(f"  backtest {idx + 1}/{len(run_list)}: {cand.id}...", flush=True)
            try:
                results.append(await run_candidate_dataset_a(cand, dataset, base_dir=base_dir))
            except Exception as exc:
                results.append({
                    "candidate_id": cand.id,
                    "title": cand.title,
                    "error": str(exc),
                })

    _write("datasetA_results.json", {
        "phase": "22I",
        "dataset": dataset.to_dict(),
        "results": results,
    })

    comparison = compare_candidates(results) if results else {"phase": "22I", "ranked": []}
    _write("candidate_comparison.json", comparison)

    recommended = select_recommended(results, comparison) if results else {"phase": "22I", "selected_id": None}
    _write("recommended_policy_change.json", recommended)

    largest = profile.get("largest_hold_loss") or {}
    verdict = (
        "READY_FOR_DECISION_IMPLEMENTATION"
        if recommended.get("selected_id") and not profile.get("error")
        else "MORE_DECISION_RESEARCH_REQUIRED"
    )

    final = {
        "phase": "22I",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "evidence_driven_decision_engine_research",
        "production_modified": False,
        "dataset": dataset.to_dict(),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "verdict": verdict,
        "final_questions": {
            "1_largest_hold_loss": largest.get("reason"),
            "2_highest_roi_policy": recommended.get("selected_id"),
            "3_expected_pf_improvement": recommended.get("predicted_impact", {}).get("profit_factor_improvement"),
            "4_expected_trade_frequency_improvement_pct": recommended.get("predicted_impact", {}).get("trade_frequency_improvement_pct"),
            "5_engineering_risk": recommended.get("predicted_impact", {}).get("engineering_risk"),
        },
        "hold_histogram_top3": profile.get("hold_histogram", [])[:3],
        "recommended": recommended,
        "comparison_best": comparison.get("best_candidate_id"),
    }
    _write("phase22i_final_report.json", final)

    print(f"\nPhase 22I complete | verdict={verdict} | {final['elapsed_sec']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
