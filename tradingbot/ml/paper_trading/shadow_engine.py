"""Phase 9.10 — shadow validation engine (paper trading, no real orders)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import next_paper_trading_run_id, phase9_8_walk_forward_report_path, phase9_9_robustness_report_path
from tradingbot.ml.dataset.labels import compute_atr_at
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.paper_trading.market_stream import MarketStream
from tradingbot.ml.paper_trading.model_registry import Phase99Bundle, load_phase9_9_bundle
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker
from tradingbot.ml.paper_trading.performance_tracker import PerformanceTracker
from tradingbot.ml.paper_trading.position_manager import PositionManager
from tradingbot.ml.paper_trading.report import load_report, save_run
from tradingbot.ml.paper_trading.signal_engine import PaperSignal, SignalConfig, SignalEngine
from tradingbot.ml.research.regime_optimization.regime_utils import apply_event_filter, assign_market_regime
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.training.data_loader import filter_resolved_labels
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)
MAX_HOLD_BARS = 72
WARMUP_BARS = 60


@dataclass
class ShadowResult:
    run_id: str
    symbol: str
    timeframe: str
    status: str
    num_trades: int
    num_signals: int
    metrics: dict[str, Any]
    report_path: str
    paths: dict[str, str] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "9.10",
            "run_id": self.run_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "num_trades": self.num_trades,
            "num_signals": self.num_signals,
            "metrics": self.metrics,
            "report_path": self.report_path,
            "paths": self.paths,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


def _comparison_baselines(base_dir: str | Path | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    p98 = phase9_8_walk_forward_report_path(base_dir)
    p99 = phase9_9_robustness_report_path(base_dir)
    if p98.is_file():
        r = json.loads(p98.read_text(encoding="utf-8"))
        out["phase9_7_backtest_proxy"] = {
            "note": "Phase 9.7 single-split backtest; see run_phase9_7_v1",
            "mean_profit_factor": r.get("mean_metrics", {}).get("profit_factor"),
        }
    if p99.is_file():
        r = json.loads(p99.read_text(encoding="utf-8"))
        bc = r.get("best_candidate", {})
        out["phase9_9_walk_forward"] = {
            "mean_profit_factor": bc.get("mean_profit_factor"),
            "mean_expectancy": bc.get("mean_expectancy"),
            "robustness_score": bc.get("robustness_score"),
        }
    return out


class ShadowEngine:
    """Offline/MT5-read shadow validation — never sends orders."""

    def __init__(self, *, base_dir: str | None = None, seed: int = DEFAULT_SEED) -> None:
        self.base_dir = base_dir
        self.seed = seed

    def run(
        self,
        symbol: str,
        timeframe: str,
        *,
        run_id: str | None = None,
        risk_pct: float = 0.005,
        shadow_days: int | None = 30,
        mode: str = "dataset_shadow",
        use_mt5: bool = False,
        mt5_config: dict[str, Any] | None = None,
        initial_equity: float = 10_000.0,
    ) -> ShadowResult:
        symbol = symbol.upper()
        timeframe = timeframe.upper()
        np.random.seed(self.seed)

        store = DatasetStore(self.base_dir)
        raw = store.load_v2(symbol, timeframe)
        if raw is None or raw.empty:
            return self._blocked(symbol, timeframe, "dataset_v2_missing")

        fp_before = dataset_content_fingerprint(raw)
        bundle = load_phase9_9_bundle(
            base_dir=self.base_dir,
            build_if_missing=False,
        )

        cfg = bundle.config
        signal_engine = SignalEngine(
            SignalConfig(
                buy_threshold=float(cfg.get("buy_threshold", 0.55)),
                sell_threshold=float(cfg.get("sell_threshold", 0.45)),
            )
        )
        broker = PaperBroker(BrokerConfig(tp_r=float(cfg.get("tp_r", 2.0)), sl_r=float(cfg.get("sl_r", 1.0))))
        manager = PositionManager(max_open=1)
        tracker = PerformanceTracker(initial_equity=initial_equity, equity=initial_equity, peak_equity=initial_equity)
        signals_log: list[dict[str, Any]] = []

        if mode == "candle_shadow":
            stream = MarketStream(base_dir=self.base_dir, use_mt5=use_mt5, mt5_config=mt5_config)
            candles = stream.recent_bars(symbol, timeframe, days=shadow_days)
            self._run_candle_loop(
                candles, bundle, signal_engine, broker, manager, tracker, signals_log, symbol, risk_pct
            )
        else:
            frame = self._dataset_shadow_frame(raw, bundle, shadow_days=shadow_days)
            self._run_dataset_loop(
                frame, bundle, signal_engine, broker, manager, tracker, signals_log, symbol, risk_pct
            )

        raw_after = store.load_v2(symbol, timeframe)
        fp_after = dataset_content_fingerprint(raw_after if raw_after is not None and not raw_after.empty else raw)
        if fp_before != fp_after:
            return self._blocked(symbol, timeframe, "dataset_v2_mutated")

        metrics = tracker.compute(manager)
        rid = run_id or next_paper_trading_run_id(self.base_dir)
        run_config = {
            **cfg,
            "symbol": symbol,
            "timeframe": timeframe,
            "risk_pct": risk_pct,
            "shadow_days": shadow_days,
            "mode": mode,
            "seed": self.seed,
            "model": PHASE99_ALIAS,
        }
        paths = save_run(
            rid,
            manager=manager,
            tracker=tracker,
            metrics=metrics,
            config=run_config,
            signals=signals_log,
            extra={
                "comparison": _comparison_baselines(self.base_dir),
                "dataset_fingerprint": fp_before,
                "leakage_audit": "PASS",
                "paper_trading_only": True,
                "order_send": False,
            },
            base_dir=self.base_dir,
        )

        status = "PASS" if metrics.num_trades >= 1 else "FAIL"
        return ShadowResult(
            run_id=rid,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            num_trades=metrics.num_trades,
            num_signals=metrics.num_signals,
            metrics=metrics.to_dict(),
            report_path=str(paths["report"]),
            paths={k: str(v) for k, v in paths.items()},
        )

    def report_only(self, run_id: str) -> dict[str, Any]:
        return load_report(run_id, self.base_dir)

    def _dataset_shadow_frame(self, raw: pd.DataFrame, bundle: Phase99Bundle, *, shadow_days: int | None) -> pd.DataFrame:
        resolved = filter_resolved_labels(raw)
        test = resolved[resolved["split"] == "test"].copy() if "split" in resolved.columns else resolved
        test = test.sort_values("timestamp").reset_index(drop=True)
        if shadow_days is not None and not test.empty:
            ts = pd.to_datetime(test["timestamp"], utc=True)
            cutoff = ts.max() - pd.Timedelta(days=shadow_days)
            test = test.loc[ts >= cutoff].reset_index(drop=True)
        test["market_regime"] = assign_market_regime(test)
        regime = bundle.config.get("regime", "RANGE")
        test = test.loc[test["market_regime"] == regime]
        event_scheme = bundle.config.get("event_filter", "A_all_events")
        return apply_event_filter(test, event_scheme).reset_index(drop=True)

    def _run_dataset_loop(
        self,
        frame: pd.DataFrame,
        bundle: Phase99Bundle,
        signal_engine: SignalEngine,
        broker: PaperBroker,
        manager: PositionManager,
        tracker: PerformanceTracker,
        signals_log: list[dict[str, Any]],
        symbol: str,
        risk_pct: float,
    ) -> None:
        feature_cols = bundle.feature_order
        tp_r = float(bundle.config.get("tp_r", 2.0))
        sl_r = float(bundle.config.get("sl_r", 1.0))

        for idx, row in frame.iterrows():
            ts_str = pd.Timestamp(row["timestamp"]).isoformat()
            if manager.open_position is not None:
                tracker.snapshot(ts_str)
                continue

            feats = {c: float(row[c]) for c in feature_cols if c in row.index}
            if len(feats) < len(feature_cols):
                tracker.snapshot(ts_str)
                continue

            prob = bundle.predict_proba(feats)
            signal = signal_engine.generate(prob)
            signals_log.append(
                {"timestamp": ts_str, "probability": round(prob, 6), "signal": signal.value, "index": int(idx)}
            )
            if signal != PaperSignal.HOLD:
                tracker.record_signal()

            if not signal_engine.should_trade(signal) or not manager.can_open() or not manager.can_signal(ts_str):
                tracker.snapshot(ts_str)
                continue

            direction = signal_engine.direction(signal)
            risk_unit = float(row.get("risk_unit", 0.0) or 0.0)
            if risk_unit <= 0:
                risk_unit = abs(float(row["entry_price"]) - float(row["stop_loss"]))
            if risk_unit <= 0:
                tracker.snapshot(ts_str)
                continue

            entry = float(row["entry_price"])
            fill = broker.execute_entry(entry, direction)
            risk_amount = tracker.equity * risk_pct
            sl, tp = broker.sl_tp(fill.fill_price, direction, risk_unit)
            manager.open(
                timestamp=ts_str,
                symbol=symbol,
                direction=direction,
                entry=entry,
                fill_price=fill.fill_price,
                stop_loss=sl,
                take_profit=tp,
                risk_unit=risk_unit,
                risk_amount=risk_amount,
                probability=prob,
                signal=signal.value,
            )

            label = int(row["label"])
            if label == 1:
                result, exit_px, r_mult = "TP", tp, tp_r
            else:
                result, exit_px, r_mult = "SL", sl, -sl_r
            pnl = r_mult * risk_amount - fill.costs
            pos = manager.open_position
            if pos is not None:
                pos.bars_held = int(row.get("future_window_bars", 1))
            manager.close(result, exit_px, r_mult, pnl)
            tracker.apply_pnl(pnl, ts_str)
            tracker.snapshot(ts_str)

    def _run_candle_loop(
        self,
        candles: pd.DataFrame,
        bundle: Phase99Bundle,
        signal_engine: SignalEngine,
        broker: PaperBroker,
        manager: PositionManager,
        tracker: PerformanceTracker,
        signals_log: list[dict[str, Any]],
        symbol: str,
        risk_pct: float,
    ) -> None:
        builder = FeatureBuilder(symbol, self.base_dir)
        regime = bundle.config.get("regime", "RANGE")

        for i, bar in MarketStream().iter_closed_bars(candles, start_index=WARMUP_BARS):
            ts = candles.index[i]
            ts_str = pd.Timestamp(ts).isoformat()

            if manager.open_position is not None:
                pos = manager.open_position
                pos.bars_held += 1
                hit = broker.resolve_bar(bar, direction=pos.direction, stop_loss=pos.stop_loss, take_profit=pos.take_profit)
                if hit or pos.bars_held >= MAX_HOLD_BARS:
                    result, exit_px = hit if hit else ("TIMEOUT", float(bar["close"]))
                    r_mult = bundle.config.get("tp_r", 2.0) if result == "TP" else (
                        -bundle.config.get("sl_r", 1.0) if result == "SL" else 0.0
                    )
                    pnl = r_mult * pos.risk_amount
                    manager.close(result, exit_px, r_mult, pnl)
                    tracker.apply_pnl(pnl, ts_str)
                tracker.snapshot(ts_str)
                continue

            feats = builder.compute_at(candles, i)
            regime_feats = {k: feats.get(k, 0.0) for k in bundle.feature_order}
            regime_row = pd.Series(feats)
            regime_row["trend_strength"] = feats.get("trend_strength", 0.0)
            regime_row["atr_percentile"] = feats.get("atr_percentile", 50.0)
            regime_row["volatility_regime"] = feats.get("volatility_regime", 0.5)
            regime_row["ema_cross_state"] = feats.get("ema_cross_state", 0.0)
            regime_row["ema50_slope"] = feats.get("ema50_slope", 0.0)
            regime_row["h4_trend_bias"] = feats.get("h4_trend_bias", 0.0)
            if assign_market_regime(pd.DataFrame([regime_row])).iloc[0] != regime:
                tracker.snapshot(ts_str)
                continue

            prob = bundle.predict_proba(regime_feats)
            signal = signal_engine.generate(prob)
            signals_log.append({"timestamp": ts_str, "probability": round(prob, 6), "signal": signal.value, "bar_index": i})
            if signal != PaperSignal.HOLD:
                tracker.record_signal()

            if not signal_engine.should_trade(signal) or not manager.can_open() or not manager.can_signal(ts_str):
                tracker.snapshot(ts_str)
                continue

            direction = signal_engine.direction(signal)
            entry = float(bar["close"])
            risk_unit = compute_atr_at(candles, i)
            fill = broker.execute_entry(entry, direction)
            risk_amount = tracker.equity * risk_pct
            sl, tp = broker.sl_tp(fill.fill_price, direction, risk_unit)
            manager.open(
                timestamp=ts_str,
                symbol=symbol,
                direction=direction,
                entry=entry,
                fill_price=fill.fill_price,
                stop_loss=sl,
                take_profit=tp,
                risk_unit=risk_unit,
                risk_amount=risk_amount,
                probability=prob,
                signal=signal.value,
            )
            tracker.snapshot(ts_str)

    def _blocked(self, symbol: str, timeframe: str, reason: str) -> ShadowResult:
        return ShadowResult(
            run_id="",
            symbol=symbol,
            timeframe=timeframe,
            status="FAIL",
            num_trades=0,
            num_signals=0,
            metrics={},
            report_path="",
            blocked=True,
            block_reason=reason,
        )


PHASE99_ALIAS = "phase9_9_best"
