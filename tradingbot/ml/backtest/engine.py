"""Event-driven backtest engine for Phase 8.7."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.backtest.broker_sim import BrokerConfig, SimulatedBroker
from tradingbot.ml.backtest.metrics import BacktestMetrics, compute_metrics
from tradingbot.ml.backtest.report import allocate_run_id, load_backtest_run, save_backtest_run
from tradingbot.ml.backtest.risk import RiskConfig, RiskManager
from tradingbot.ml.backtest.state import BacktestState, SignalAction, SimulatedTrade, TradeStatus
from tradingbot.ml.backtest.strategy import StrategyConfig, ThresholdStrategy
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.training.data_loader import filter_resolved_labels
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import TrainingModel
from tradingbot.ml.training.model_registry import load_model_bundle, resolve_model_path

logger = logging.getLogger(__name__)
DEFAULT_SEED = 42


@dataclass
class BacktestConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    initial_equity: float = 10_000.0
    seed: int = DEFAULT_SEED
    split: str = "test"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "initial_equity": self.initial_equity,
            "seed": self.seed,
            "split": self.split,
            "strategy": asdict(self.strategy),
            "risk": asdict(self.risk),
            "broker": asdict(self.broker),
        }


@dataclass
class BacktestResult:
    run_id: str
    symbol: str
    timeframe: str
    model_version: str
    metrics: BacktestMetrics
    paths: dict[str, str] = field(default_factory=dict)
    num_signals: int = 0
    num_trades: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "model_version": self.model_version,
            "metrics": self.metrics.to_dict(),
            "paths": self.paths,
            "num_signals": self.num_signals,
            "num_trades": self.num_trades,
        }


def _extract_model_version(model_path: Path) -> str:
    match = re.search(r"model_v(\d+)", model_path.stem)
    if match:
        return match.group(1)
    meta_candidates = model_path.parent.glob("metadata_v*.json")
    for meta in sorted(meta_candidates):
        return meta.stem.replace("metadata_v", "")
    raise ValueError(f"Cannot resolve model version from {model_path}")


def _load_bundle_from_model_arg(model_arg: str, base_dir: str | Path | None) -> tuple[TrainingModel, FeaturePipeline, str, dict[str, Any]]:
    path = resolve_model_path(model_arg, base_dir)
    version = _extract_model_version(path)
    bundle = load_model_bundle(version, base_dir)
    return bundle.model, bundle.feature_pipeline, version, bundle.metadata


def _prepare_backtest_frame(
    symbol: str,
    timeframe: str,
    split: str,
    base_dir: str | Path | None,
) -> pd.DataFrame:
    store = DatasetStore(base_dir)
    df = store.load_v2(symbol, timeframe)
    if df is None or df.empty:
        raise FileNotFoundError(f"Dataset v2 not found for {symbol} {timeframe}")
    filtered = filter_resolved_labels(df)
    if split and split.lower() != "all":
        part = filtered[filtered["split"] == split.lower()].copy()
        if part.empty:
            raise ValueError(f"No rows in split={split!r}")
        filtered = part
    sort_cols = [c for c in ("timestamp", "event_id") if c in filtered.columns]
    return filtered.sort_values(sort_cols or ["timestamp"]).reset_index(drop=True)


def _verify_sequential(timestamps: pd.Series) -> None:
    ts = pd.to_datetime(timestamps, utc=True)
    if not ts.is_monotonic_increasing:
        raise ValueError("Backtest frame is not chronologically ordered")


class BacktestEngine:
    """Deterministic offline backtest on dataset_v2 with Phase 8.6 model artifacts."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir

    def run(
        self,
        model_arg: str,
        config: BacktestConfig | None = None,
        *,
        run_id: str | None = None,
    ) -> BacktestResult:
        cfg = config or BacktestConfig()
        np.random.seed(cfg.seed)

        model, pipeline, version, metadata = _load_bundle_from_model_arg(model_arg, self.base_dir)
        frame = _prepare_backtest_frame(cfg.symbol, cfg.timeframe, cfg.split, self.base_dir)
        _verify_sequential(frame["timestamp"])

        strategy = ThresholdStrategy(cfg.strategy)
        risk_mgr = RiskManager(cfg.risk)
        broker = SimulatedBroker(cfg.broker)

        state = BacktestState(initial_equity=cfg.initial_equity, equity=cfg.initial_equity, peak_equity=cfg.initial_equity)
        state.record_equity(str(frame["timestamp"].iloc[0]))

        feature_cols = pipeline.feature_order
        missing = [c for c in feature_cols if c not in frame.columns]
        if missing:
            raise ValueError(f"Dataset missing features for backtest: {missing[:5]}")

        for idx, row in frame.iterrows():
            ts_str = pd.Timestamp(row["timestamp"]).isoformat()
            X_row = pd.DataFrame([row[feature_cols].astype(np.float64)])
            X_scaled = pipeline.transform(X_row)
            proba = model.predict_proba(X_scaled)[0]
            prob_tp = float(proba[1])
            pred_class = int(model.predict(X_scaled)[0])
            signal = strategy.generate_signal(prob_tp)

            state.signals.append(
                {
                    "index": int(idx),
                    "timestamp": ts_str,
                    "probability": round(prob_tp, 6),
                    "predicted_class": pred_class,
                    "signal": signal.value,
                    "label": int(row["label"]),
                }
            )

            if not strategy.should_trade(signal):
                state.record_equity(ts_str)
                continue

            if not state.can_open_trade(cfg.risk.max_open_trades):
                state.record_equity(ts_str)
                continue

            event_dir = int(row.get("direction", 1))
            trade_dir = strategy.trade_direction(signal, event_dir)
            if trade_dir == 0:
                state.record_equity(ts_str)
                continue

            risk_unit = float(row.get("risk_unit", 0.0))
            if risk_unit <= 0:
                entry = float(row["entry_price"])
                sl = float(row["stop_loss"])
                risk_unit = abs(entry - sl)
            if risk_unit <= 0:
                state.record_equity(ts_str)
                continue

            position = risk_mgr.compute_position(state.equity, risk_unit)
            entry_price = float(row["entry_price"])
            fill = broker.execute_entry(entry_price, trade_dir)
            costs = broker.execution_cost_r(risk_unit, position.risk_amount)
            label = int(row["label"])
            pnl, pnl_r = risk_mgr.pnl_from_label(label, position.risk_amount, costs=costs)
            exit_price = broker.resolve_exit_price(label, float(row["stop_loss"]), float(row["take_profit"]))

            state.trade_counter += 1
            trade = SimulatedTrade(
                trade_id=state.trade_counter,
                event_id=str(row.get("event_id", f"row_{idx}")),
                timestamp=ts_str,
                symbol=cfg.symbol.upper(),
                signal=signal,
                direction=trade_dir,
                entry_price=entry_price,
                stop_loss=float(row["stop_loss"]),
                take_profit=float(row["take_profit"]),
                risk_unit=risk_unit,
                risk_amount=position.risk_amount,
                fill_price=fill.fill_price,
                probability=prob_tp,
                predicted_class=pred_class,
                label=label,
                status=TradeStatus.CLOSED,
                exit_price=exit_price,
                pnl=pnl,
                pnl_r=pnl_r,
                costs=costs,
                bars_held=int(row.get("future_window_bars", 0)),
                split=str(row.get("split", "")),
            )
            state.close_open_trade(trade)
            state.record_equity(ts_str)

        metrics = compute_metrics(state)
        rid = run_id or allocate_run_id(self.base_dir)
        config_payload = {
            **cfg.to_dict(),
            "model_arg": model_arg,
            "model_version": version,
            "model_metadata": metadata,
            "rows_simulated": len(frame),
        }
        paths = save_backtest_run(
            rid,
            state,
            metrics,
            config_payload,
            base_dir=self.base_dir,
            extra={
                "symbol": cfg.symbol.upper(),
                "timeframe": cfg.timeframe.upper(),
                "model_version": version,
            },
        )

        return BacktestResult(
            run_id=rid,
            symbol=cfg.symbol.upper(),
            timeframe=cfg.timeframe.upper(),
            model_version=version,
            metrics=metrics,
            paths={k: str(v) for k, v in paths.items()},
            num_signals=sum(1 for s in state.signals if s["signal"] != SignalAction.HOLD.value),
            num_trades=len(state.closed_trades),
        )

    def report_only(self, run_id: str) -> dict[str, Any]:
        return load_backtest_run(run_id, self.base_dir)

    @staticmethod
    def verify_no_future_features(frame: pd.DataFrame, current_idx: int, feature_cols: list[str]) -> bool:
        """Guardrail: features at index i must not depend on rows > i (timestamp check)."""
        if current_idx <= 0:
            return True
        ts = pd.to_datetime(frame["timestamp"], utc=True)
        return ts.iloc[current_idx] >= ts.iloc[:current_idx].max()
