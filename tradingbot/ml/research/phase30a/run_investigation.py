"""Phase 30A — real market execution simulator research orchestrator."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.execution.execution_costs import (
    session_from_hour,
    slippage_magnitude_points,
    slippage_probability,
    spread_distribution_samples,
)
from tradingbot.execution.execution_latency import latency_distribution_samples
from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, ExecutionScenario, OrderSide
from tradingbot.execution.execution_simulator import ExecutionSimulator, context_from_trade
from tradingbot.execution.market_impact import market_impact_summary
from tradingbot.ml.research.phase28d.trade_builder import trades_from_replay_meta
from tradingbot.ml.research.phase30a.breaking_points import find_breaking_points
from tradingbot.ml.research.phase30a.pipeline_audit import build_execution_pipeline_map
from tradingbot.ml.research.phase30a.trade_replay import replay_trades_with_execution

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE29B_CACHE = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase29b" / "_cache" / "wpsqf" / "replay_meta.json"

STRESS_SCENARIOS = [
    ExecutionScenario.NORMAL,
    ExecutionScenario.HIGH_SPREAD,
    ExecutionScenario.HIGH_SLIPPAGE,
    ExecutionScenario.HIGH_LATENCY,
    ExecutionScenario.LOW_LIQUIDITY,
    ExecutionScenario.NEWS,
    ExecutionScenario.FLASH_CRASH,
    ExecutionScenario.WEEKEND,
]

VERDICTS = {
    "EXECUTION_LAYER_VALIDATED",
    "EXECUTION_LAYER_NEEDS_IMPROVEMENT",
    "NOT_READY_FOR_PRODUCTION",
}


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_trades() -> list[dict[str, Any]]:
    if not PHASE29B_CACHE.is_file():
        raise FileNotFoundError("Phase 29B WPSQF replay_meta.json required")
    meta = json.loads(PHASE29B_CACHE.read_text(encoding="utf-8"))
    return trades_from_replay_meta(meta)


def _build_contexts(trades: list[dict[str, Any]]) -> list[ExecutionContext]:
    contexts: list[ExecutionContext] = []
    for t in trades:
        hour = 12
        try:
            hour = __import__("pandas").Timestamp(t["timestamp"]).hour
        except Exception:
            pass
        ctx = context_from_trade(t, hour=hour)
        contexts.append(ctx)
    return contexts


def _slippage_distribution(contexts: list[ExecutionContext], profile: ExecutionProfile) -> dict[str, Any]:
    sim = ExecutionSimulator(profile)
    slips: list[float] = []
    signs: dict[str, int] = {"negative": 0, "zero": 0, "positive": 0}
    for ctx in contexts:
        result = sim.simulate(ctx)
        slips.append(result.outcome.slippage_points)
        if result.outcome.slippage_sign < 0:
            signs["negative"] += 1
        elif result.outcome.slippage_sign > 0:
            signs["positive"] += 1
        else:
            signs["zero"] += 1
    n = len(slips) or 1
    s = sorted(slips)
    return {
        "phase": "30A",
        "count": len(slips),
        "mean": round(sum(slips) / n, 4),
        "p50": round(s[len(s) // 2], 4) if s else 0,
        "p95": round(s[int(len(s) * 0.95)], 4) if s else 0,
        "sign_distribution": {k: round(v / n * 100, 2) for k, v in signs.items()},
        "probability_model_sample": slippage_probability(contexts[0], profile) if contexts else {},
        "magnitude_model_sample": slippage_magnitude_points(contexts[0], profile) if contexts else 0,
    }


def _determine_verdict(normal_pf: float, stress_results: dict[str, Any], breaking: dict[str, Any]) -> str:
    if normal_pf < 1.0:
        return "NOT_READY_FOR_PRODUCTION"
    flash = stress_results.get(ExecutionScenario.FLASH_CRASH.value, {})
    flash_pf = float(flash.get("performance", {}).get("profit_factor", 0) or 0)
    if normal_pf >= 1.1 and flash_pf >= 0.85:
        return "EXECUTION_LAYER_VALIDATED"
    if normal_pf >= 1.0:
        return "EXECUTION_LAYER_NEEDS_IMPROVEMENT"
    return "NOT_READY_FOR_PRODUCTION"


def run_phase30a(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    pipeline_map = build_execution_pipeline_map()
    _write("execution_pipeline_map.json", pipeline_map)

    trades = _load_trades()
    contexts = _build_contexts(trades)
    base_profile = ExecutionProfile(scenario=ExecutionScenario.NORMAL, seed=42)

    spread_dist = spread_distribution_samples(contexts, base_profile)
    spread_dist["phase"] = "30A"
    spread_dist["generated_utc"] = ts
    _write("spread_distribution.json", spread_dist)

    slip_dist = _slippage_distribution(contexts, base_profile)
    slip_dist["generated_utc"] = ts
    _write("slippage_distribution.json", slip_dist)

    latency_dist = latency_distribution_samples(contexts, base_profile, seed=42)
    latency_dist["phase"] = "30A"
    latency_dist["generated_utc"] = ts
    _write("latency_distribution.json", latency_dist)

    sim = ExecutionSimulator(base_profile)
    impacts = [sim.simulate(c).outcome.market_impact_points for c in contexts[:200]]
    impact_summary = market_impact_summary(impacts)
    impact_summary["phase"] = "30A"
    impact_summary["generated_utc"] = ts
    _write("market_impact.json", impact_summary)

    normal_replay = replay_trades_with_execution(trades, base_profile)
    _write("fill_statistics.json", {**normal_replay["fill_stats"], "phase": "30A", "generated_utc": ts})
    _write("execution_quality.json", {**normal_replay["execution_quality"], "phase": "30A", "generated_utc": ts})

    stress_results: dict[str, Any] = {}
    for scenario in STRESS_SCENARIOS:
        profile = ExecutionProfile(scenario=scenario, seed=42)
        replay = replay_trades_with_execution(trades, profile)
        stress_results[scenario.value] = {
            "performance": replay["performance"],
            "execution_quality": replay["execution_quality"],
            "fill_stats": replay["fill_stats"],
        }
    _write("stress_tests.json", {"phase": "30A", "scenarios": stress_results, "generated_utc": ts})

    baseline_perf = normal_replay["performance"]
    breaking = find_breaking_points(trades, replay_trades_with_execution, base_profile=base_profile)
    breaking["generated_utc"] = ts
    _write("execution_breaking_points.json", breaking)

    phase29b_meta = json.loads(PHASE29B_CACHE.read_text(encoding="utf-8"))
    ref_perf = (phase29b_meta.get("accounting") or {}).get("performance") or {}

    comparison = {
        "phase": "30A",
        "baseline_source": "phase29b_wpsqf",
        "trade_count": len(trades),
        "ideal_execution": {
            k: ref_perf.get(k)
            for k in (
                "profit_factor", "expectancy", "net_profit", "max_drawdown_pct",
                "win_rate_pct", "sharpe_ratio", "recovery_factor", "completed_trades",
            )
        },
        "simulated_normal_execution": {
            k: normal_replay["performance"].get(k)
            for k in (
                "profit_factor", "expectancy", "net_profit", "max_drawdown_pct",
                "win_rate_pct", "sharpe_ratio", "recovery_factor", "completed_trades",
            )
        },
        "stress_summary": {
            k: v["performance"].get("profit_factor") for k, v in stress_results.items()
        },
        "generated_utc": ts,
    }
    _write("performance_comparison.json", comparison)

    normal_pf = float(normal_replay["performance"].get("profit_factor", 0) or 0)
    verdict = _determine_verdict(normal_pf, stress_results, breaking)

    recommendation = {
        "phase": "30A",
        "verdict": verdict,
        "filter_name": "Real Market Execution Simulator",
        "research_only": True,
        "production_integration": False,
        "normal_pf": normal_pf,
        "breaking_points_summary": {
            "spread": breaking["max_spread_multiplier_before_pf_lt_1"].get("breaking_point"),
            "slippage": breaking["max_slippage_multiplier_before_pf_lt_1"].get("breaking_point"),
            "latency_delay": breaking["max_latency_multiplier_before_pf_lt_1"].get("breaking_point"),
            "market_impact": breaking["max_market_impact_multiplier_before_pf_lt_1"].get("breaking_point"),
        },
        "recommendation": (
            "Proceed to Phase 30B production adapter integration with session-aware spread and slippage models."
            if verdict == "EXECUTION_LAYER_VALIDATED"
            else "Improve liquidity and flash-crash handling before production wiring."
            if verdict == "EXECUTION_LAYER_NEEDS_IMPROVEMENT"
            else "Execution degradation too severe under realistic costs — recalibrate before production."
        ),
        "generated_utc": ts,
    }
    _write("production_recommendation.json", recommendation)

    final = {
        "phase": "30A",
        "verdict": verdict,
        "explanation": (
            f"Execution simulator built under tradingbot/execution/. "
            f"Replayed {len(trades)} Phase 29B trades. Normal scenario PF={normal_pf:.3f}. "
            f"Breaking spread multiplier={breaking['max_spread_multiplier_before_pf_lt_1'].get('breaking_point')}."
        ),
        "deliverables": [
            "execution_pipeline_map.json",
            "spread_distribution.json",
            "slippage_distribution.json",
            "latency_distribution.json",
            "market_impact.json",
            "fill_statistics.json",
            "execution_quality.json",
            "stress_tests.json",
            "execution_breaking_points.json",
            "performance_comparison.json",
            "production_recommendation.json",
            "phase30a_final_report.json",
        ],
        "production_modified": False,
        "generated_utc": ts,
    }
    _write("phase30a_final_report.json", final)
    return final


def main() -> int:
    report = run_phase30a()
    print(json.dumps({"verdict": report["verdict"], "explanation": report["explanation"]}, indent=2))
    return 0 if report["verdict"] != "NOT_READY_FOR_PRODUCTION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
