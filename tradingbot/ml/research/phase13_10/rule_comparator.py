"""Phase 13.10 — trend rule variant comparison (A–D)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_10.robust_score import count_trend_trades, threshold_composite_score
from tradingbot.ml.research.phase13_10.trend_engines import build_trend_adapter
from tradingbot.ml.research.phase13_10.config import RULE_VARIANT_KEYS
from tradingbot.ml.research.phase13_10.walk_forward import quick_wf_score_for_config
from tradingbot.ml.research.phase13_8.trend_variants import VARIANTS
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import run_unified_router_backtest
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams


def _count_rule_signals(frame: pd.DataFrame, rule_fn, regimes: pd.Series) -> int:
    n = 0
    for i in range(len(frame)):
        if str(regimes.iloc[i]) != "TREND":
            continue
        if rule_fn(frame.iloc[i], regime="TREND") in ("BUY", "SELL"):
            n += 1
    return n


def compare_trend_rule_variants(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    model: Any,
    scaler: Any,
    model_name: str,
    threshold: float,
    seed: int = 42,
    symbol: str = "XAUUSD",
    base_dir: str | None = None,
    engine_cache: EngineCache | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    cache = engine_cache or EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)
    unified = build_unified_frame(candles, dataset)
    regimes = rule_classify(unified)
    keys = RULE_VARIANT_KEYS[:2] if quick else RULE_VARIANT_KEYS
    rows: list[dict[str, Any]] = []

    for key in keys:
        label, rule_fn = VARIANTS[key]
        signal_count = _count_rule_signals(unified, rule_fn, regimes)
        adapter = build_trend_adapter(
            model=model,
            scaler=scaler,
            model_name=model_name,
            threshold=threshold,
            rule_fn=rule_fn,
            symbol=symbol,
        )
        cfg = OptimizerConfig(
            regime_params=RegimeThresholdParams(),
            policy="A",
            trend_ml_threshold=threshold,
            seed=seed,
            symbol=symbol,
        )
        bt = run_unified_router_backtest(
            candles,
            dataset,
            config=cfg,
            seed=seed,
            symbol=symbol,
            base_dir=base_dir,
            engine_cache=cache,
            trend_adapter=adapter,
        )
        m = bt["metrics"]
        trend_trades = count_trend_trades(bt)
        wf = quick_wf_score_for_config(
            candles,
            dataset,
            config=cfg,
            trend_adapter=adapter,
            seed=seed,
            symbol=symbol,
            base_dir=base_dir,
            quick=quick,
        )
        rows.append(
            {
                "variant": key,
                "label": label,
                "signal_count": signal_count,
                "accepted_trades": int(m.get("trades", 0)),
                "trend_trades": trend_trades,
                "profit_factor": round(float(m.get("profit_factor", 0.0)), 4),
                "expectancy": round(float(m.get("expectancy", m.get("expectancy_r", 0.0))), 4),
                "max_drawdown": round(float(m.get("max_drawdown", 0.0)), 4),
                "walk_forward_score": round(wf, 4),
                "stability_score": threshold_composite_score(m, walk_forward_score=wf),
                "chronological": True,
                "shuffle": False,
            }
        )

    ranked = sorted(rows, key=lambda r: r["stability_score"], reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i

    return {
        "phase": "13.10",
        "variants_tested": list(keys),
        "threshold": threshold,
        "results": rows,
        "best_variant": ranked[0]["variant"] if ranked else None,
        "ranking": ranked,
        "chronological": True,
        "shuffle": False,
    }
