"""Phase 13.5 — router validation and integrity checks."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle, verify_bundle_integrity
from tradingbot.ml.research.regime_router.config import RouterConfig
from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
from tradingbot.ml.research.regime_router.regime_router import route_regime
from tradingbot.ml.research.regime_router.trend_engine_adapter import TrendEngineAdapter
from tradingbot.ml.research.regime_router.walk_forward_router import run_router_backtest, run_walk_forward_router


def validate_router_components(
    candles: pd.DataFrame,
    *,
    config: RouterConfig,
    base_dir: str | None = None,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    try:
        bundle = load_phase9_9_bundle(base_dir=None, build_if_missing=False)
        integrity = verify_bundle_integrity(bundle, {f: 0.0 for f in bundle.feature_order})
        checks["phase9_9_loaded"] = integrity.passed
        if not integrity.passed:
            errors.extend(integrity.errors)
    except Exception as exc:
        checks["phase9_9_loaded"] = False
        errors.append(f"phase9_9: {exc}")

    try:
        range_engine = RangeEngineAdapter.load(symbol=config.symbol, base_dir=base_dir)
        checks["range_engine_loaded"] = range_engine is not None
    except Exception as exc:
        checks["range_engine_loaded"] = False
        errors.append(f"range_engine: {exc}")

    try:
        trend_engine = TrendEngineAdapter.load(
            candles,
            symbol=config.symbol,
            base_dir=base_dir,
            seed=config.seed,
            threshold=config.trend_ml_threshold,
        )
        checks["trend_engine_loaded"] = trend_engine is not None
    except Exception as exc:
        checks["trend_engine_loaded"] = False
        errors.append(f"trend_engine: {exc}")

    routing = {
        "RANGE": route_regime("RANGE"),
        "TREND": route_regime("TREND"),
        "HIGH_VOLATILITY": route_regime("HIGH_VOLATILITY"),
        "NO_TRADE": route_regime("NO_TRADE"),
    }
    checks["regime_routing"] = routing == {
        "RANGE": "RANGE",
        "TREND": "TREND",
        "HIGH_VOLATILITY": "BLOCK",
        "NO_TRADE": "BLOCK",
    }
    if not checks["regime_routing"]:
        errors.append(f"unexpected routing map: {routing}")

    status = "PASS" if all(checks.values()) else "FAIL"
    return {"status": status, "checks": checks, "errors": errors}


def validate_router_backtest(
    candles: pd.DataFrame,
    *,
    config: RouterConfig,
    base_dir: str | None = None,
    dataset: pd.DataFrame | None = None,
) -> dict[str, Any]:
    component = validate_router_components(candles, config=config, base_dir=base_dir)
    backtest = run_router_backtest(candles, config=config, base_dir=base_dir, dataset=dataset)
    walk_forward = run_walk_forward_router(candles, config=config, base_dir=base_dir, dataset=dataset)

    wf_ok = all(w.get("shuffle") is False for w in walk_forward["windows"] if not w.get("skipped"))
    return {
        "component_validation": component,
        "backtest": backtest,
        "walk_forward": walk_forward,
        "chronological": backtest["chronological"],
        "shuffle": backtest["shuffle"],
        "walk_forward_integrity": wf_ok,
        "status": "PASS" if component["status"] == "PASS" and wf_ok else "NEEDS_REVIEW",
    }
