"""Paper trading report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.paper._types import PaperConfig, SignalMode
from tradingbot.ml.paper.engine import PaperTradingEngine
from tradingbot.ml.paper.metrics import compute_metrics
from tradingbot.ml.paper.portfolio import Portfolio
from tradingbot.ml.paper.walk_forward_runner import WalkForwardRunner


def paper_trading_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "paper_trading_report.json"


def write_paper_report(payload: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    path = paper_trading_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


class PaperReportGenerator:
    """Run simulation and write paper_trading_report.json."""

    def __init__(
        self,
        *,
        config: PaperConfig | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self.config = config or PaperConfig(deterministic=True)
        self.base_dir = base_dir

    def run(
        self,
        symbol: str,
        timeframe: str,
        signal_mode: SignalMode = SignalMode.HYBRID,
    ) -> dict[str, Any]:
        candles = self._load_candles(symbol, timeframe)
        decisions = DecisionMemoryStore(symbol, self.base_dir).load_decisions()

        if candles is None or candles.empty:
            candles = self._load_candles_from_dataset(symbol, timeframe)

        engine = PaperTradingEngine(config=self.config, signal_mode=signal_mode)
        simulation = engine.run(candles, decisions) if candles is not None and not candles.empty else {
            "metrics": compute_metrics(Portfolio(initial_balance_r=self.config.initial_balance_r)).to_dict(),
            "equity_curve": [self.config.initial_balance_r],
            "closed_trades": [],
            "session_breakdown": {},
            "slippage_impact": {},
            "signal_mode": signal_mode.value,
        }

        comparison = {}
        if candles is not None and not candles.empty and decisions:
            comparison = engine.compare_modes(candles, decisions)

        walk_forward = []
        if candles is not None and not candles.empty and decisions:
            walk_forward = [
                w.to_dict()
                for w in WalkForwardRunner(config=self.config).run(candles, decisions, signal_mode=signal_mode)
            ]

        payload = {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "signal_mode": signal_mode.value,
            "status": "SIMULATION COMPLETE",
            "metrics": simulation["metrics"],
            "equity_curve": simulation["equity_curve"],
            "trades": simulation.get("closed_trades", []),
            "session_breakdown": simulation.get("session_breakdown", {}),
            "slippage_impact": simulation.get("slippage_impact", {}),
            "model_comparison": comparison,
            "walk_forward": walk_forward,
        }
        write_paper_report(payload, self.base_dir)
        return payload

    def _load_candles(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        from tradingbot.ml.data.stores.candle_store import CandleStore

        return CandleStore(self.base_dir).load(symbol, timeframe)

    def _load_candles_from_dataset(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        df = DatasetStore(self.base_dir).load(symbol, timeframe)
        if df is None or df.empty:
            return None
        cols = [c for c in ("timestamp", "open", "high", "low", "close") if c in df.columns]
        if "high" not in df.columns:
            return None
        out = df[cols].copy() if cols else df.copy()
        if "timestamp" not in out.columns and "event_time" in df.columns:
            out["timestamp"] = df["event_time"]
        if "close" not in out.columns and "entry_price" in df.columns:
            out["close"] = df["entry_price"]
            out["open"] = df["entry_price"]
            out["high"] = df["entry_price"] * 1.001
            out["low"] = df["entry_price"] * 0.999
        return out
