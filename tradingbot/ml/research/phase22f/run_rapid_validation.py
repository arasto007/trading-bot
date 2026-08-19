#!/usr/bin/env python3
"""Phase 22F — rapid optimization framework (read-only, evidence-driven)."""

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


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 22F rapid validation")
    parser.add_argument("--dataset", default="A", choices=["A", "B", "C"])
    parser.add_argument("--characterize-all", action="store_true", help="Profile datasets A/B/C without full backtest")
    args = parser.parse_args(argv)

    from tradingbot.ml.research.phase22f.ablation import build_feature_contribution
    from tradingbot.ml.research.phase22f.bottleneck import build_bottleneck_map
    from tradingbot.ml.research.phase22f.config import TIMEFRAMES, build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import build_all_datasets, load_ohlcv_for_dataset
    from tradingbot.ml.research.phase22f.missed_ops import analyze_missed_opportunities
    from tradingbot.ml.research.phase22f.overfiltering import analyze_overfiltering
    from tradingbot.ml.research.phase22f.priority import build_priority_list
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest
    from tradingbot.ml.research.phase22f.trade_quality import analyze_trade_quality
    from tradingbot.ml.research.phase22f.workflow import build_development_workflow

    configure_research_env()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    print(f"Phase 22F | dataset={args.dataset} | output={OUT}", flush=True)

    all_ds = await build_all_datasets()
    dataset = build_dataset(args.dataset)
    framework = {
        "phase": "22F",
        "mode": "rapid_validation",
        "primary_dataset": args.dataset,
        "datasets": all_ds,
        "target_runtime_min": "5-15",
        "production_modified": False,
        "timeframes": list(TIMEFRAMES),
    }
    _write("rapid_validation_framework.json", framework)

    baseline_by_tf: dict = {}
    for tf in TIMEFRAMES:
        print(f"  backtest {tf} dataset {args.dataset}...", flush=True)
        try:
            result = await run_rapid_backtest(tf, dataset)
            baseline_by_tf[tf] = result
            s = result.get("summary", {})
            print(
                f"    trades={result.get('trades')} PF={s.get('profit_factor')} "
                f"exp={s.get('expectancy')} ({result.get('elapsed_sec')}s)",
                flush=True,
            )
        except Exception as exc:
            print(f"    SKIP {tf}: {exc}", flush=True)
            baseline_by_tf[tf] = {"error": str(exc), "timeframe": tf}

    m5 = baseline_by_tf.get("M5", {})
    baseline_snapshot = {
        "phase": "22F",
        "dataset": dataset.to_dict(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "per_timeframe": {tf: baseline_by_tf[tf].get("summary", baseline_by_tf[tf]) for tf in TIMEFRAMES},
        "metrics": {tf: baseline_by_tf[tf].get("metrics", {}) for tf in TIMEFRAMES},
        "hold_chain": {tf: baseline_by_tf[tf].get("hold_chain", {}) for tf in TIMEFRAMES},
        "elapsed_sec": {tf: baseline_by_tf[tf].get("elapsed_sec") for tf in TIMEFRAMES},
    }
    _write("baseline_snapshot.json", baseline_snapshot)

    ohlcv_m5 = await load_ohlcv_for_dataset(dataset, "M5")
    missed = analyze_missed_opportunities(
        m5.get("blocked_events") or [],
        ohlcv_m5,
        timeframe="M5",
    )
    _write("missed_opportunities.json", missed)

    contribution = build_feature_contribution(baseline_by_tf, missed)
    _write("feature_contribution.json", contribution)

    bottleneck = build_bottleneck_map(baseline_by_tf)
    _write("signal_bottleneck_map.json", bottleneck)

    tq = {
        "phase": "22F",
        "per_timeframe": {},
    }
    for tf in TIMEFRAMES:
        frame = await load_ohlcv_for_dataset(dataset, tf) if tf != "M5" else ohlcv_m5
        tq["per_timeframe"][tf] = analyze_trade_quality(
            baseline_by_tf[tf].get("trades_detail") or [],
            frame,
            timeframe=tf,
        )
    _write("trade_quality.json", tq)

    overfiltering = analyze_overfiltering(baseline_by_tf, missed)
    _write("overfiltering_analysis.json", overfiltering)

    priority = build_priority_list(contribution, overfiltering, missed, baseline_by_tf)
    _write("optimization_priority.json", priority)

    workflow = build_development_workflow()
    _write("development_workflow.json", workflow)

    top = priority.get("top_recommendation") or {}
    m5_metrics = m5.get("metrics") or {}
    pf = m5_metrics.get("profit_factor", 0)
    pf_val = float(pf) if pf not in ("inf", None) else 0.0

    final = {
        "phase": "22F",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": args.dataset,
        "elapsed_total_sec": round(time.perf_counter() - t0, 1),
        "production_modified": False,
        "optimization_implemented": False,
        "verdict": "READY_FOR_FAST_OPTIMIZATION" if baseline_by_tf.get("M5", {}).get("trades") is not None else "MORE_INVESTIGATION_REQUIRED",
        "final_questions": {
            "1_biggest_bottleneck": _biggest_bottleneck(bottleneck, contribution),
            "2_highest_roi_improvement": top.get("recommendation", "Insufficient evidence"),
            "3_module_hurts_most": _hurts_most(contribution, m5_metrics),
            "4_module_contributes_most": _contributes_most(baseline_by_tf),
            "5_optimize_next_before_long_cert": priority.get("candidates", [{}])[0].get("component", "riskgate") if priority.get("candidates") else "riskgate",
        },
        "baseline_m5": {
            "trades": m5.get("trades"),
            "profit_factor": pf_val,
            "expectancy": m5_metrics.get("expectancy"),
            "max_drawdown_pct": m5_metrics.get("max_drawdown_pct"),
        },
        "overfiltering": overfiltering.get("verdict"),
        "priority_top_3": (priority.get("candidates") or [])[:3],
    }
    _write("phase22f_final_report.json", final)

    print(f"\nPhase 22F complete | verdict={final['verdict']} | {final['elapsed_total_sec']}s", flush=True)
    return 0


def _biggest_bottleneck(bottleneck: dict, contribution: dict) -> str:
    comps = contribution.get("components") or []
    if comps:
        top = comps[0]
        return f"{top['component']} ({top['blocks_total']} blocks, {top['pct_of_bars_total']}% of bars)"
    rg = bottleneck.get("combined_stage_losses", {})
    if rg:
        stage = max(rg, key=rg.get)
        return f"{stage} ({rg[stage]} cumulative losses)"
    return "unknown — insufficient baseline data"


def _hurts_most(contribution: dict, metrics: dict) -> str:
    comps = contribution.get("components") or []
    rg = next((c for c in comps if c["component"] == "riskgate"), None)
    if rg and rg["blocks_total"] > 100:
        reasons = rg.get("reasons") or {}
        top_reason = max(reasons, key=reasons.get) if reasons else "unknown"
        return f"riskgate ({rg['blocks_total']} blocks; dominant: {top_reason})"
    pf = float(metrics.get("profit_factor") or 0)
    if pf < 1.0:
        return "net_negative_expectancy (all modules combined — PF < 1)"
    return comps[0]["component"] if comps else "unknown"


def _contributes_most(baseline_by_tf: dict) -> str:
    engines: dict[str, int] = {}
    for tf, r in baseline_by_tf.items():
        util = (r.get("summary") or {}).get("model_utilization") or {}
        for k, v in util.items():
            engines[k] = engines.get(k, 0) + v
    if engines:
        top = max(engines, key=engines.get)
        return f"{top} ({engines[top]} routed signals)"
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
