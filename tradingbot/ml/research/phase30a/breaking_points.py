"""Discover execution breaking points — max stress before PF < 1."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from tradingbot.execution.execution_models import ExecutionProfile


def _pf_from_replay(replay: dict[str, Any]) -> float:
    pf = replay.get("performance", {}).get("profit_factor")
    if isinstance(pf, (int, float)):
        return float(pf)
    return 0.0


def _sweep_parameter(
    trades: list[dict[str, Any]],
    replay_fn: Callable,
    *,
    param_name: str,
    values: list[float],
    base_profile: ExecutionProfile,
) -> dict[str, Any]:
    results = []
    breaking = None
    for val in values:
        profile = replace(base_profile, **{param_name: val})
        replay = replay_fn(trades, profile)
        pf = _pf_from_replay(replay)
        results.append({"value": val, "profit_factor": pf, "net_profit": replay["performance"].get("net_profit")})
        if pf < 1.0 and breaking is None:
            breaking = val
    return {
        "parameter": param_name,
        "sweep": results,
        "breaking_point": breaking,
        "max_safe_value": results[-2]["value"] if breaking and len(results) > 1 else (results[-1]["value"] if results else None),
    }


def find_breaking_points(
    trades: list[dict[str, Any]],
    replay_fn: Callable,
    *,
    base_profile: ExecutionProfile | None = None,
    sample_size: int = 120,
) -> dict[str, Any]:
    base = base_profile or ExecutionProfile()
    sample = trades[:sample_size] if len(trades) > sample_size else trades
    spread_vals = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    slip_vals = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]
    latency_vals = [1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0]
    delay_vals = [1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0]
    impact_vals = [1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0]

    return {
        "phase": "30A",
        "baseline_scenario": base.scenario.value,
        "max_spread_multiplier_before_pf_lt_1": _sweep_parameter(
            sample, replay_fn, param_name="spread_multiplier", values=spread_vals, base_profile=base
        ),
        "max_slippage_multiplier_before_pf_lt_1": _sweep_parameter(
            sample, replay_fn, param_name="slippage_multiplier", values=slip_vals, base_profile=base
        ),
        "max_latency_multiplier_before_pf_lt_1": _sweep_parameter(
            sample, replay_fn, param_name="delay_multiplier", values=latency_vals, base_profile=base
        ),
        "max_execution_delay_multiplier_before_pf_lt_1": _sweep_parameter(
            sample, replay_fn, param_name="delay_multiplier", values=delay_vals, base_profile=base
        ),
        "max_market_impact_multiplier_before_pf_lt_1": _sweep_parameter(
            sample, replay_fn, param_name="impact_multiplier", values=impact_vals, base_profile=base
        ),
        "sample_size": len(sample),
    }
