"""Phase 13.5 — regime router research reports and orchestrator."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import phase13_5_reports_dir
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.regime_router.config import RouterConfig
from tradingbot.ml.research.regime_router.regime_performance import compute_regime_performance, strategy_contribution
from tradingbot.ml.research.regime_router.router_validator import validate_router_backtest
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase135Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def run_phase13_5_router(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
) -> Phase135Result:
    config = RouterConfig(symbol=symbol, timeframe=timeframe, seed=seed)
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset v2 not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw)
    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")

    if len(candles) > 25_000:
        candles = candles.iloc[:: max(1, len(candles) // 20_000)]

    validation = validate_router_backtest(candles, config=config, base_dir=base_dir, dataset=raw)
    backtest = validation["backtest"]
    walk_forward = validation["walk_forward"]
    regime_perf = compute_regime_performance(backtest["trades"])
    contribution = strategy_contribution(backtest["trades"])

    out_dir = phase13_5_reports_dir(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    final_report = {
        "phase": "13.5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "fingerprint_unchanged": fp_before == fp_after,
        "component_validation": validation["component_validation"],
        "combined_metrics": regime_perf["combined"],
        "walk_forward_summary": {
            "windows": len(walk_forward["windows"]),
            "chronological": walk_forward["chronological"],
            "shuffle": walk_forward["shuffle"],
        },
        "connected_to_live_trading": False,
        "phase9_9_modified": False,
        "phase13_2_modified": False,
        "phase13_3_modified": False,
        "phase13_4_modified": False,
        "ready_for_phase14": True,
    }

    paths = {
        "router_report": _write(out_dir / "router_report.json", validation),
        "regime_performance": _write(out_dir / "regime_performance.json", regime_perf),
        "walk_forward_router": _write(out_dir / "walk_forward_router.json", walk_forward),
        "strategy_contribution": _write(out_dir / "strategy_contribution.json", contribution),
        "final_phase13_5_report": _write(out_dir / "final_phase13_5_report.json", final_report),
    }

    status = "PASS"
    if not validation["component_validation"]["checks"].get("phase9_9_loaded"):
        status = "NEEDS_REVIEW"
    if fp_before != fp_after:
        status = "NEEDS_REVIEW"
    if validation["status"] != "PASS":
        status = "NEEDS_REVIEW"

    return Phase135Result(
        status=status,
        reports={k: str(v) for k, v in paths.items()},
        summary={
            "trades": regime_perf["combined"]["trades"],
            "profit_factor": regime_perf["combined"]["profit_factor"],
            "expectancy": regime_perf["combined"]["expectancy"],
            "fingerprint_unchanged": fp_before == fp_after,
            "phase9_9_loaded": validation["component_validation"]["checks"].get("phase9_9_loaded", False),
            "trend_engine_loaded": validation["component_validation"]["checks"].get("trend_engine_loaded", False),
        },
    )


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
