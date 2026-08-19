"""Phase 16B — hard-check validator and final verdict."""

from __future__ import annotations

from typing import Any


def _check_trend_nonzero(window_results: dict[str, Any]) -> tuple[bool, str]:
    for stride_data in window_results.get("strides", {}).values():
        trend = stride_data.get("engine_health", {}).get("TREND", {})
        actionable = trend.get("buy", 0) + trend.get("sell", 0)
        if actionable > 0:
            return True, ""
    return False, "TREND signals dropped to zero"


def _check_psi(alignment: dict[str, Any]) -> tuple[bool, str]:
    max_psi = alignment.get("max_psi_after", 0.0)
    if max_psi > 1.0:
        return False, f"PSI after alignment {max_psi} > 1.0"
    return True, ""


def _check_range_contribution(window_results: dict[str, Any]) -> tuple[bool, str]:
    for stride_data in window_results.get("strides", {}).values():
        k = stride_data.get("kernel", {})
        if k.get("actionable", 0) > 0 and k.get("range_contribution", 0) == 0:
            return False, "RANGE contribution disappeared"
    return True, ""


def _check_inflation(inflation_pct: float, max_pct: float = 20.0) -> tuple[bool, str]:
    if inflation_pct > max_pct:
        return False, f"Signal inflation {inflation_pct:.1f}% > {max_pct}%"
    return True, ""


def _check_cross_window_stability(windows: dict[str, Any]) -> tuple[bool, str]:
    rates = []
    for wk, wdata in windows.items():
        for sd in wdata.get("strides", {}).values():
            rates.append(sd.get("engine_health", {}).get("TREND", {}).get("actionable_rate", 0.0))
    if len(rates) < 2:
        return True, ""
    mean_r = sum(rates) / len(rates)
    var = sum((r - mean_r) ** 2 for r in rates) / len(rates)
    if mean_r > 0 and var > 0.01:
        return False, f"Cross-window TREND rate variance {var:.4f} too high"
    return True, ""


def _any_trend_nonzero(windows: dict[str, Any]) -> tuple[bool, str]:
    for wdata in windows.values():
        ok, _ = _check_trend_nonzero(wdata)
        if ok:
            return True, ""
    return False, "TREND signals dropped to zero"


def _any_range_present(windows: dict[str, Any]) -> tuple[bool, str]:
    for wdata in windows.values():
        for stride_data in wdata.get("strides", {}).values():
            k = stride_data.get("kernel", {})
            if k.get("range_contribution", 0) > 0:
                return True, ""
            eng = stride_data.get("engine_health", {}).get("RANGE", {})
            if eng.get("buy", 0) + eng.get("sell", 0) > 0:
                return True, ""
    return False, "RANGE contribution disappeared"


def run_hard_checks(
    *,
    windows: dict[str, Any],
    alignment_stability: dict[str, Any],
    inflation_pct: float,
) -> dict[str, Any]:
    failures: list[str] = []
    for check_fn in (
        lambda: _any_trend_nonzero(windows),
        lambda: _check_psi(alignment_stability),
        lambda: _any_range_present(windows),
        lambda: _check_inflation(inflation_pct),
        lambda: _check_cross_window_stability(windows),
    ):
        ok, msg = check_fn()
        if not ok and msg:
            failures.append(msg)

    return {"passed": len(failures) == 0, "failures": failures}


def final_verdict(
    hard_checks: dict[str, Any],
    windows: dict[str, Any],
    stress: dict[str, Any],
) -> str:
    if not hard_checks.get("passed"):
        return "NEEDS_REWORK"

    stress_ok = all(
        stress.get(k, {}).get("passed", True)
        for k in ("regime_shock", "distribution_shift", "threshold_sensitivity")
    )
    if not stress_ok:
        return "NEEDS_MINOR_TUNING"

    trend_rates = []
    for wdata in windows.values():
        for sd in wdata.get("strides", {}).values():
            trend_rates.append(sd.get("engine_health", {}).get("TREND", {}).get("actionable_rate", 0.0))

    if max(trend_rates, default=0) < 0.001:
        return "NEEDS_MINOR_TUNING"

    if hard_checks.get("passed") and stress_ok:
        return "READY_FOR_PHASE16C"
    return "NEEDS_MINOR_TUNING"
