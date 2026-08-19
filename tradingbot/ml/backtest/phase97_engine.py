"""Phase 9.7 production backtest engine using Phase 9.6 research artifacts."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.backtest.broker_sim import BrokerConfig, SimulatedBroker
from tradingbot.ml.backtest.engine import BacktestConfig, BacktestResult, _prepare_backtest_frame, _verify_sequential
from tradingbot.ml.backtest.metrics import BacktestMetrics, compute_metrics
from tradingbot.ml.backtest.model_loader import (
    IntegrityResult,
    Phase96ModelBundle,
    load_phase9_6_bundle,
    verify_integrity,
)
from tradingbot.ml.backtest.report import load_backtest_run, save_backtest_run
from tradingbot.ml.backtest.risk import RiskConfig, RiskManager
from tradingbot.ml.backtest.strategy import StrategyConfig, ThresholdStrategy
from tradingbot.ml.backtest.state import BacktestState, SimulatedTrade, TradeStatus
from tradingbot.ml.backtest.trade_state import TradeStateMachine
from tradingbot.ml.data.paths import phase9_7_default_run_id
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.regime_optimization.regime_utils import apply_event_filter, assign_market_regime
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.training.data_loader import filter_resolved_labels

logger = logging.getLogger(__name__)


@dataclass
class Phase97BacktestResult(BacktestResult):
    integrity: IntegrityResult | None = None
    leakage_audit: str = "PASS"
    paper_trading_ready: bool = False
    best_threshold: dict[str, float] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload.update(
            {
                "phase": "9.7",
                "integrity": asdict(self.integrity) if self.integrity else None,
                "leakage_audit": self.leakage_audit,
                "paper_trading_ready": self.paper_trading_ready,
                "best_threshold": self.best_threshold,
                "recommendation": self.recommendation,
            }
        )
        return payload


def _apply_phase96_filters(
    df: pd.DataFrame,
    *,
    regime: str,
    event_scheme: str,
) -> pd.DataFrame:
    work = df.copy()
    work["market_regime"] = assign_market_regime(work)
    work = work.loc[work["market_regime"] == regime]
    return apply_event_filter(work, event_scheme).sort_values("timestamp").reset_index(drop=True)


def _paper_trading_assessment(metrics: BacktestMetrics, num_trades: int) -> tuple[bool, str]:
    if num_trades < 1:
        return False, "MORE RESEARCH REQUIRED — no trades executed"
    if metrics.expectancy_r > 0 and metrics.profit_factor >= 1.0 and metrics.total_return > 0:
        return True, "READY FOR PAPER TRADING"
    if metrics.expectancy_r > 0 and metrics.profit_factor >= 1.2:
        return True, "READY FOR PAPER TRADING"
    return False, "MORE RESEARCH REQUIRED — backtest metrics below paper-trading threshold"


class Phase97BacktestEngine:
    """Offline strategy validation for Phase 9.6 RANGE + XGBoost configuration."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = base_dir

    def run(
        self,
        config: BacktestConfig | None = None,
        *,
        run_id: str | None = None,
        seed: int = 42,
    ) -> Phase97BacktestResult:
        cfg = config or BacktestConfig()
        np.random.seed(seed)

        bundle = load_phase9_6_bundle(
            base_dir=self.base_dir,
            build_if_missing=True,
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            seed=seed,
        )
        regime = bundle.configuration.get("regime", "RANGE")
        event_scheme = bundle.configuration.get("event_filter", "A_all_events")

        store = DatasetStore(self.base_dir)
        raw = store.load_v2(cfg.symbol, cfg.timeframe)
        if raw is None or raw.empty:
            raise FileNotFoundError(f"dataset_v2 missing for {cfg.symbol} {cfg.timeframe}")

        fingerprint_before = dataset_content_fingerprint(raw)
        integrity = verify_integrity(bundle, raw, expected_fingerprint=bundle.dataset_fingerprint)
        if not integrity.passed:
            raise ValueError(f"Integrity check failed: {integrity.errors}")

        resolved = filter_resolved_labels(raw)
        frame = _prepare_backtest_frame(cfg.symbol, cfg.timeframe, cfg.split, self.base_dir)
        frame = _apply_phase96_filters(frame, regime=regime, event_scheme=event_scheme)
        if frame.empty:
            raise ValueError(f"No rows after Phase 9.6 filters regime={regime} event={event_scheme}")
        _verify_sequential(frame["timestamp"])

        strategy = ThresholdStrategy(cfg.strategy)
        risk_mgr = RiskManager(cfg.risk)
        broker = SimulatedBroker(cfg.broker)
        machine = TradeStateMachine()

        state = BacktestState(initial_equity=cfg.initial_equity, equity=cfg.initial_equity, peak_equity=cfg.initial_equity)
        state.record_equity(str(frame["timestamp"].iloc[0]))

        missing = [c for c in bundle.feature_order if c not in frame.columns]
        if missing:
            raise ValueError(f"Backtest frame missing features: {missing}")

        for idx, row in frame.iterrows():
            ts_str = pd.Timestamp(row["timestamp"]).isoformat()
            X = bundle.transform_row(row)
            proba = bundle.model.predict_proba(X)[0]
            prob_tp = float(proba[1])
            pred_class = int(bundle.model.predict(X)[0])
            signal = strategy.generate_signal(prob_tp)

            state.signals.append(
                {
                    "index": int(idx),
                    "timestamp": ts_str,
                    "probability": round(prob_tp, 6),
                    "predicted_class": pred_class,
                    "signal": signal.value,
                    "label": int(row["label"]),
                    "market_regime": str(row.get("market_regime", regime)),
                }
            )

            if not strategy.should_trade(signal) or not machine.can_enter(cfg.risk.max_open_trades):
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
            atr = float(row.get("atr_14", 0.0) or 0.0)
            if risk_unit <= 0 and atr <= 0:
                state.record_equity(ts_str)
                continue

            position = risk_mgr.compute_position(state.equity, risk_unit, atr=atr if atr > 0 else None)
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
            machine.enter(trade)
            machine.close(trade)
            state.close_open_trade(trade)
            state.record_equity(ts_str)

        metrics = compute_metrics(state)
        ready, recommendation = _paper_trading_assessment(metrics, len(state.closed_trades))
        rid = run_id or phase9_7_default_run_id()

        raw_after = store.load_v2(cfg.symbol, cfg.timeframe)
        fp_after = dataset_content_fingerprint(raw_after) if raw_after is not None else ""
        leakage = "PASS" if fingerprint_before == fp_after else "FAIL"

        config_payload = {
            **cfg.to_dict(),
            "phase": "9.7",
            "model": "phase9_6_best",
            "phase9_6_configuration": bundle.configuration,
            "feature_order": bundle.feature_order,
            "rows_simulated": len(frame),
            "regime_filter": regime,
            "event_filter": event_scheme,
            "integrity": asdict(integrity),
            "dataset_fingerprint": fingerprint_before,
            "dataset_fingerprint_unchanged": fingerprint_before == fp_after,
        }
        paths = save_backtest_run(
            rid,
            state,
            metrics,
            config_payload,
            base_dir=self.base_dir,
            extra={
                "phase": "9.7",
                "symbol": cfg.symbol.upper(),
                "timeframe": cfg.timeframe.upper(),
                "model": "phase9_6_best",
                "leakage_audit": leakage,
                "paper_trading_ready": ready,
                "recommendation": recommendation,
                "best_threshold": {
                    "buy_threshold": cfg.strategy.buy_threshold,
                    "sell_threshold": cfg.strategy.sell_threshold,
                },
            },
        )

        return Phase97BacktestResult(
            run_id=rid,
            symbol=cfg.symbol.upper(),
            timeframe=cfg.timeframe.upper(),
            model_version="phase9_6_best",
            metrics=metrics,
            paths={k: str(v) for k, v in paths.items()},
            num_signals=sum(1 for s in state.signals if s["signal"] != "HOLD"),
            num_trades=len(state.closed_trades),
            integrity=integrity,
            leakage_audit=leakage,
            paper_trading_ready=ready,
            best_threshold={
                "buy_threshold": cfg.strategy.buy_threshold,
                "sell_threshold": cfg.strategy.sell_threshold,
            },
            recommendation=recommendation,
        )

    def report_only(self, run_id: str) -> dict[str, Any]:
        return load_backtest_run(run_id, self.base_dir)
