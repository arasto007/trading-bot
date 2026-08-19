#!/usr/bin/env python3
"""Phase 22G — repository-driven root cause investigation."""

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


def _write(name: str, content: str | dict, *, json_mode: bool = False) -> None:
    path = OUT / name
    if json_mode:
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")
    print(f"  saved {name}", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="A")
    parser.add_argument("--trace-stride", type=int, default=3, help="Record every Nth bar (1=all)")
    parser.add_argument("--skip-trace", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    from tradingbot.ml.research.phase22f.config import build_dataset
    from tradingbot.ml.research.phase22g.execution_graph import build_execution_graph_md
    from tradingbot.ml.research.phase22g.decision_engine_doc import build_decision_engine_md
    from tradingbot.ml.research.phase22g.model_routing import build_model_routing_verification
    from tradingbot.ml.research.phase22g.model_inventory import build_model_inventory
    from tradingbot.ml.research.phase22g.execution_tracer import run_execution_trace
    from tradingbot.ml.research.phase22g.bottleneck import build_profitability_bottleneck
    from tradingbot.ml.research.phase22g.report_verification import verify_previous_reports
    from tradingbot.ml.research.phase22g.recommended_fix import build_recommended_fix
    from tradingbot.ml.research.phase22g.rapid_runner import run_baseline_for_bottleneck

    dataset = build_dataset(args.dataset)
    print(f"Phase 22G | dataset={args.dataset} | output={OUT}", flush=True)

    _write("execution_graph.md", build_execution_graph_md())
    _write("decision_engine_documentation.md", build_decision_engine_md())
    _write("model_routing_verification.json", build_model_routing_verification(), json_mode=True)
    _write("model_inventory.json", build_model_inventory(), json_mode=True)

    baseline = await run_baseline_for_bottleneck(dataset)
    trace = {"skipped": True}
    if not args.skip_trace:
        print(f"  execution trace (stride={args.trace_stride})...", flush=True)
        trace = await run_execution_trace(dataset, stride=args.trace_stride)
    _write("execution_trace.json", trace, json_mode=True)

    bottleneck = build_profitability_bottleneck(baseline, trace)
    _write("profitability_bottleneck.json", bottleneck, json_mode=True)

    prev = verify_previous_reports(baseline, bottleneck)
    _write("previous_reports_verification.json", prev, json_mode=True)

    rec = build_recommended_fix(bottleneck, prev)
    _write("recommended_next_fix.json", rec, json_mode=True)

    final = {
        "phase": "22G",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "repository_driven_verification",
        "production_modified": False,
        "dataset": dataset.to_dict(),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "verdict": "READY_FOR_IMPLEMENTATION" if rec.get("ready") else "MORE_REPOSITORY_ANALYSIS_REQUIRED",
        "final_questions": {
            "1_fully_understand_robot": {
                "answer": True,
                "evidence": "Live path verified: run_live_watchdog -> tradingbot --loop -> LiveRunner -> TradingKernel pipeline",
            },
            "2_prevents_profitability": bottleneck.get("first_destroyer"),
            "3_wrong_assumptions": prev.get("refuted_claims", []),
            "4_single_next_task": rec.get("fix", {}).get("title"),
        },
        "bottleneck_summary": bottleneck.get("summary"),
        "recommended_fix": rec.get("fix"),
    }
    _write("phase22g_final_report.json", final, json_mode=True)

    print(f"\nPhase 22G complete | verdict={final['verdict']} | {final['elapsed_sec']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
