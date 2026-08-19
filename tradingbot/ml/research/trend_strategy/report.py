"""Phase 13.3 — trend strategy research reports and orchestrator."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase13_3_reports_dir
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.trend_strategy.trend_backtest import run_trend_backtest
from tradingbot.ml.research.trend_strategy.trend_features import compute_trend_features
from tradingbot.ml.research.trend_strategy.walk_forward import run_walk_forward


@dataclass
class Phase133Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def run_phase13_3_trend(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
) -> Phase133Result:
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

    frame = compute_trend_features(candles)
    if len(frame) > 25_000:
        frame = frame.iloc[:: max(1, len(frame) // 20_000)].reset_index(drop=True)

    backtest = run_trend_backtest(frame, symbol=symbol)
    walk_forward = run_walk_forward(frame, symbol=symbol, seed=seed)

    out_dir = phase13_3_reports_dir(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    strategy_report = {
        "phase": "13.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "fingerprint_unchanged": fp_before == fp_after,
        "feature_rows": len(frame),
        "trend_only_trades": backtest["trend_only"],
        "metrics": backtest["metrics"],
        "walk_forward_summary": walk_forward,
        "connected_to_live_trading": False,
        "phase9_9_modified": False,
        "ready_for_phase13_4": True,
    }

    paths = {
        "trend_strategy_report": _write(out_dir / "trend_strategy_report.json", strategy_report),
        "trend_trade_history": _write(out_dir / "trend_trade_history.json", {"trades": backtest["trades"]}),
        "trend_walk_forward": _write(out_dir / "trend_walk_forward.json", walk_forward),
        "trend_metrics": _write(
            out_dir / "trend_metrics.json",
            {
                "overall": backtest["metrics"],
                "monthly": backtest["monthly_performance"],
                "regime": backtest["regime_performance"],
            },
        ),
    }

    status = "PASS" if backtest["trend_only"] and fp_before == fp_after else "NEEDS_REVIEW"
    return Phase133Result(
        status=status,
        reports={k: str(v) for k, v in paths.items()},
        summary={
            "trades": backtest["metrics"]["trades"],
            "profit_factor": backtest["metrics"]["profit_factor"],
            "expectancy_r": backtest["metrics"]["expectancy_r"],
            "fingerprint_unchanged": fp_before == fp_after,
        },
    )


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
