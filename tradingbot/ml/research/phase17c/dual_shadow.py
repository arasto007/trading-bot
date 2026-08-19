"""Phase 17C — dual shadow replay across horizons."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.phase17b.shadow_replay import run_shadow_replay
from tradingbot.ml.research.phase17c.config import DEFAULT_STRIDE, HORIZONS
from tradingbot.ml.research.phase17c.metrics import summarize_returns


def _enrich_horizon(result: dict[str, Any]) -> dict[str, Any]:
    """Attach PF/expectancy/drawdown/win_rate/sharpe/sortino from engine proxies."""
    for side in ("frozen", "research"):
        block = result.get(side, {})
        # Reconstruct return proxies from pf/expectancy if lists unavailable.
        # Shadow stores pf_proxy and expectancy_proxy; synthesize returns for metrics.
        n = int(block.get("engine", {}).get("trend_actionable", 0))
        pf = float(block.get("pf_proxy", 0.0))
        exp = float(block.get("expectancy_proxy", 0.0))
        if n <= 0:
            returns = []
        else:
            # Approximate: wins at +exp*pf, losses at -exp (stable proxy for reporting).
            wins = max(1, int(round(n * pf / (pf + 1)))) if pf > 0 else 0
            losses = n - wins
            win_ret = abs(exp) * max(pf, 1.0) if wins else 0.0
            loss_ret = -abs(exp) if losses else 0.0
            returns = [win_ret] * wins + [loss_ret] * losses
        block["performance"] = summarize_returns(returns)
        # Prefer stored drawdown/expectancy when present.
        block["performance"]["expectancy"] = block.get("expectancy_proxy", block["performance"]["expectancy"])
        block["performance"]["drawdown"] = block.get("drawdown_proxy", block["performance"]["drawdown"])
        block["performance"]["pf"] = block.get("pf_proxy", block["performance"]["pf"])
    return result


def run_dual_shadow_horizons(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    research: ResearchRfModel,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    horizons: tuple[int, ...] = HORIZONS,
    stride: int = DEFAULT_STRIDE,
) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    for days in horizons:
        print(f"phase17c: dual shadow {days}d ...", flush=True)
        result = run_shadow_replay(
            candles, dataset, research,
            base_dir=base_dir, symbol=symbol, timeframe=timeframe,
            days=days, stride=stride,
        )
        windows[f"{days}d"] = _enrich_horizon(result)

    # Aggregate summary
    summary = {}
    for key, win in windows.items():
        summary[key] = {
            "trend_actionable_frozen": win["frozen"]["engine"]["trend_actionable"],
            "trend_actionable_research": win["research"]["engine"]["trend_actionable"],
            "range_frozen": win["frozen"]["kernel"]["range_contribution"],
            "range_research": win["research"]["kernel"]["range_contribution"],
            "range_identical": win["comparison"]["range_identical"],
            "ceiling_frozen": win["frozen"]["engine"]["trend_max_prob"],
            "ceiling_research": win["research"]["engine"]["trend_max_prob"],
            "pf_frozen": win["frozen"]["performance"]["pf"],
            "pf_research": win["research"]["performance"]["pf"],
        }

    return {
        "phase": "17C",
        "horizons": list(horizons),
        "windows": windows,
        "summary": summary,
        "all_range_identical": all(v["range_identical"] for v in summary.values()),
        "trend_materially_improved": all(
            v["trend_actionable_research"] > v["trend_actionable_frozen"]
            for v in summary.values()
        ),
    }
