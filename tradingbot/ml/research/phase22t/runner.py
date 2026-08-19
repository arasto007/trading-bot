"""Phase 22T — run Dataset A backtest with baseline vs live feature source."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase22f.config import RapidDataset, configure_research_env
from tradingbot.ml.research.phase22t.compare import extract_backtest_metrics
from tradingbot.ml.research.phase22t.patch import research_stack


async def run_dataset_a_backtest(
    dataset: RapidDataset,
    *,
    use_live: bool,
    base_dir: str | None,
) -> dict[str, Any]:
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest

    configure_research_env()
    mode = "featurebuilder_live" if use_live else "current_repository"
    with research_stack(base_dir=base_dir, use_live=use_live):
        result = await run_rapid_backtest("M5", dataset)
    out = extract_backtest_metrics(result)
    out["mode"] = mode
    out["use_live_phase99"] = use_live
    out["dataset"] = dataset.to_dict()
    out["raw_hold_chain"] = result.get("hold_chain")
    return out


def pct_delta(baseline: float | int | None, live: float | int | None) -> float | None:
    if baseline is None or live is None:
        return None
    b = float(baseline)
    l = float(live)
    if b == 0 and l == 0:
        return 0.0
    if b == 0:
        return 100.0 if l != 0 else 0.0
    return round((l - b) / abs(b) * 100, 4)


def compare_runs(baseline: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "BUY", "SELL", "signal_density_pct", "decision_hold",
        "trade_count", "profit_factor", "expectancy",
    )
    deltas: dict[str, Any] = {}
    for k in keys:
        b = baseline.get(k)
        l = live.get(k)
        deltas[k] = {
            "baseline": b,
            "live": l,
            "delta": (None if b is None or l is None else round(float(l) - float(b), 6)),
            "pct_change": pct_delta(b, l),
        }
    return deltas


def determine_verdict(
    baseline: dict[str, Any],
    live: dict[str, Any],
    signal_baseline: dict[str, Any],
    signal_live: dict[str, Any],
    *,
    threshold_pct: float = 5.0,
) -> str:
    trade_deltas = compare_runs(baseline, live)
    sig_deltas = compare_runs(
        {
            "BUY": signal_baseline.get("signals", {}).get("BUY"),
            "SELL": signal_baseline.get("signals", {}).get("SELL"),
            "signal_density_pct": signal_baseline.get("signal_density_pct"),
            "decision_hold": None,
            "trade_count": None,
            "profit_factor": None,
            "expectancy": None,
        },
        {
            "BUY": signal_live.get("signals", {}).get("BUY"),
            "SELL": signal_live.get("signals", {}).get("SELL"),
            "signal_density_pct": signal_live.get("signal_density_pct"),
            "decision_hold": None,
            "trade_count": None,
            "profit_factor": None,
            "expectancy": None,
        },
    )

    material_keys = (
        "BUY", "SELL", "signal_density_pct", "decision_hold",
        "trade_count", "profit_factor", "expectancy",
    )
    any_change = False
    max_improve_pct = 0.0
    for k in material_keys:
        d = trade_deltas.get(k, {})
        b, l = d.get("baseline"), d.get("live")
        if b != l and not (b is None and l is None):
            any_change = True
        pc = d.get("pct_change")
        if pc is not None and abs(pc) > abs(max_improve_pct):
            max_improve_pct = pc

    # Engine-level signal changes
    sb = signal_baseline.get("signals", {})
    sl = signal_live.get("signals", {})
    if sb != sl:
        any_change = True
    pb = signal_baseline.get("p_win", {})
    pl = signal_live.get("p_win", {})
    if pb.get("mean") != pl.get("mean"):
        any_change = True

    if not any_change:
        return "NO_EFFECT"

    abs_effects = []
    for k in material_keys:
        pc = trade_deltas.get(k, {}).get("pct_change")
        if pc is not None:
            abs_effects.append(abs(pc))
    for k in ("BUY", "SELL", "signal_density_pct"):
        pc = sig_deltas.get(k, {}).get("pct_change")
        if pc is not None:
            abs_effects.append(abs(pc))

    max_abs = max(abs_effects) if abs_effects else 0.0
    pf_b = baseline.get("profit_factor")
    pf_l = live.get("profit_factor")
    trades_b = baseline.get("trade_count") or 0
    trades_l = live.get("trade_count") or 0

    if max_abs < threshold_pct and pf_b == pf_l and trades_b == trades_l:
        return "NO_EFFECT"
    if max_abs < threshold_pct:
        return "SMALL_EFFECT"
    if trades_l > trades_b and (pf_l or 0) > (pf_b or 0) and max_abs >= threshold_pct:
        return "PRODUCTION_READY"
    if max_abs >= threshold_pct:
        return "SIGNIFICANT_EFFECT"
    return "SMALL_EFFECT"
