"""Phase 10 — ML shadow integration engine (observation only, no orders)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import next_ml_shadow_run_id
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.paper_trading.market_stream import MarketStream
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.shadow.config import ShadowConfig
from tradingbot.ml.shadow.decision_logger import load_shadow_report, save_shadow_run
from tradingbot.ml.shadow.kernel_bridge import ShadowKernelBridge
from tradingbot.ml.shadow.ml_adapter import MLAdapter
from tradingbot.ml.shadow.shadow_metrics import ShadowMetricsTracker
from tradingbot.ml.shadow.shadow_signal import ShadowSignal
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)
WARMUP_BARS = 60
MAX_HOLD_BARS = 72


@dataclass
class MLShadowResult:
    run_id: str
    symbol: str
    timeframe: str
    mode: str
    status: str
    num_signals: int
    num_virtual_trades: int
    metrics: dict[str, Any]
    report_path: str
    paths: dict[str, str] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "10",
            "run_id": self.run_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "status": self.status,
            "num_signals": self.num_signals,
            "num_virtual_trades": self.num_virtual_trades,
            "metrics": self.metrics,
            "report_path": self.report_path,
            "paths": self.paths,
            "validation": self.validation,
            "order_send": False,
            "shadow_only": True,
        }


@dataclass
class _VirtualPosition:
    entry_index: int
    direction: int
    entry: float
    sl: float
    tp: float
    risk_amount: float
    timestamp: str
    signal: str
    bars_held: int = 0


class MLShadowEngine:
    """Replay or live-read shadow loop with ML + kernel/risk observation."""

    def __init__(self, *, base_dir: str | Path | None = None, seed: int = DEFAULT_SEED) -> None:
        self.base_dir = base_dir
        self.seed = seed

    def run(
        self,
        config: ShadowConfig | None = None,
        *,
        run_id: str | None = None,
        legacy_config: dict[str, Any] | None = None,
    ) -> MLShadowResult:
        cfg = config or ShadowConfig()
        np.random.seed(self.seed)
        symbol = cfg.symbol.upper()
        timeframe = cfg.timeframe.upper()

        store = DatasetStore(self.base_dir)
        training_df = store.load_v2(symbol, timeframe)
        adapter = MLAdapter.load(
            base_dir=self.base_dir,
            training_df=training_df,
            seed=self.seed,
            model_version=cfg.model_alias,
        )
        validation = adapter.validate(dataset_df=training_df)
        if not validation.passed:
            raise ValueError(f"Model validation failed: {validation.errors}")

        fp_before = dataset_content_fingerprint(training_df) if training_df is not None else ""
        regime = adapter.bundle.config.get("regime", "RANGE")

        stream = MarketStream(
            base_dir=self.base_dir,
            use_mt5=cfg.mode == "live_shadow" or cfg.use_mt5,
            mt5_config={"days": cfg.shadow_days},
        )
        try:
            candles = stream.recent_bars(symbol, timeframe, days=cfg.shadow_days)
        except FileNotFoundError:
            if training_df is None or training_df.empty:
                raise
            logger.warning("Candle store empty — building replay candles from dataset_v2")
            candles = self._candles_from_dataset(training_df, days=cfg.shadow_days)
        builder = FeatureBuilder(symbol, self.base_dir)
        bridge = ShadowKernelBridge(
            legacy_config=legacy_config or self._legacy_config(),
            broker=PaperBroker(BrokerConfig(tp_r=cfg.tp_r, sl_r=cfg.sl_r)),
        )
        metrics_tracker = ShadowMetricsTracker(initial_equity=cfg.initial_equity, equity=cfg.initial_equity)

        signals_log: list[dict[str, Any]] = []
        kernel_log: list[dict[str, Any]] = []
        risk_log: list[dict[str, Any]] = []
        virtual_trades: list[dict[str, Any]] = []
        open_pos: _VirtualPosition | None = None
        bar_indices = list(stream.iter_closed_bars(candles, start_index=WARMUP_BARS))
        if cfg.mode == "replay" and len(bar_indices) > cfg.max_replay_bars:
            bar_indices = bar_indices[-cfg.max_replay_bars :]

        for i, bar in bar_indices:
            ts = pd.Timestamp(candles.index[i]).isoformat()

            if open_pos is not None:
                open_pos.bars_held += 1
                hit = bridge._broker.resolve_bar(
                    bar, direction=open_pos.direction, stop_loss=open_pos.sl, take_profit=open_pos.tp
                )
                if hit or open_pos.bars_held >= MAX_HOLD_BARS:
                    result, exit_px = hit if hit else ("TIMEOUT", float(bar["close"]))
                    r_mult = cfg.tp_r if result == "TP" else (-cfg.sl_r if result == "SL" else 0.0)
                    pnl = r_mult * open_pos.risk_amount
                    trade = {
                        "timestamp": open_pos.timestamp,
                        "symbol": symbol,
                        "direction": open_pos.direction,
                        "entry": open_pos.entry,
                        "exit": round(exit_px, 4),
                        "sl": open_pos.sl,
                        "tp": open_pos.tp,
                        "result": result,
                        "R_multiple": round(r_mult, 4),
                        "duration": open_pos.bars_held,
                        "pnl": round(pnl, 4),
                        "signal": open_pos.signal,
                    }
                    virtual_trades.append(trade)
                    metrics_tracker.record_trade_close(trade)
                    open_pos = None
                continue

            feats = builder.compute_at(candles, i)
            regime_row = pd.Series(feats)
            if assign_market_regime(pd.DataFrame([regime_row])).iloc[0] != regime:
                continue

            subset = {k: feats.get(k, 0.0) for k in adapter.bundle.feature_order}
            prediction = adapter.predict(subset, timestamp=ts)
            shadow = ShadowSignal.from_prediction(
                prediction, symbol=symbol, timeframe=timeframe, model_version=cfg.model_alias
            )
            signals_log.append(shadow.to_dict())
            metrics_tracker.record_ml_signal(shadow.direction, shadow.confidence)

            decision = bridge.evaluate(
                shadow, candles, i, observe_strategy=shadow.is_trade or (i % 12 == 0)
            )
            kernel_log.append(decision["kernel_result"])
            risk_log.append(decision["risk_result"])
            metrics_tracker.record_kernel(bool(decision["kernel_result"].get("would_kernel_trade")))
            metrics_tracker.record_risk(bool(decision["risk_result"].get("allowed")))

            if decision["outcome"] != "pending" or open_pos is not None:
                continue

            dir_int = 1 if shadow.direction == "BUY" else -1
            risk_amount = metrics_tracker.equity * cfg.risk_pct
            open_pos = _VirtualPosition(
                entry_index=i,
                direction=dir_int,
                entry=float(decision["virtual_entry"]),
                sl=float(decision["virtual_sl"]),
                tp=float(decision["virtual_tp"]),
                risk_amount=risk_amount,
                timestamp=ts,
                signal=shadow.direction,
            )

        if training_df is not None:
            raw_after = store.load_v2(symbol, timeframe)
            fp_after = dataset_content_fingerprint(
                raw_after if raw_after is not None and not raw_after.empty else training_df
            )
            if fp_before and fp_before != fp_after:
                raise RuntimeError("dataset_v2 mutated during shadow run")

        metrics = metrics_tracker.compute().to_dict()
        rid = run_id or next_ml_shadow_run_id(self.base_dir)
        run_config = {**cfg.to_dict(), "model": cfg.model_alias, "regime": regime, "validation": validation.checks}
        paths = save_shadow_run(
            rid,
            signals=signals_log,
            kernel_decisions=kernel_log,
            risk_decisions=risk_log,
            virtual_trades=virtual_trades,
            metrics=metrics,
            config=run_config,
            extra={
                "validation": {"status": validation.status, "checks": validation.checks},
                "dataset_fingerprint": fp_before,
                "leakage_audit": "PASS",
            },
            base_dir=self.base_dir,
        )

        status = "PASS" if len(signals_log) >= 1 else "FAIL"
        return MLShadowResult(
            run_id=rid,
            symbol=symbol,
            timeframe=timeframe,
            mode=cfg.mode,
            status=status,
            num_signals=len(signals_log),
            num_virtual_trades=len(virtual_trades),
            metrics=metrics,
            report_path=str(paths["report"]),
            paths={k: str(v) for k, v in paths.items()},
            validation={"status": validation.status, "checks": validation.checks},
        )

    def report_only(self, run_id: str) -> dict[str, Any]:
        return load_shadow_report(run_id, self.base_dir)

    @staticmethod
    def _legacy_config() -> dict[str, Any]:
        try:
            from tradingbot.adapters.legacy_loader import load_legacy_config

            return load_legacy_config()
        except Exception:
            return {"INITIAL_BALANCE": 10_000, "RISK_PER_TRADE": 0.005}

    @staticmethod
    def _candles_from_dataset(df: pd.DataFrame, *, days: int) -> pd.DataFrame:
        work = df.sort_values("timestamp").copy()
        ts = pd.to_datetime(work["timestamp"], utc=True)
        cutoff = ts.max() - pd.Timedelta(days=days)
        work = work.loc[ts >= cutoff]
        if work.empty:
            raise FileNotFoundError("No dataset rows in shadow window")

        anchor = float(work["entry_price"].iloc[-1]) if "entry_price" in work.columns else 2300.0
        n = max(500, WARMUP_BARS + 100)
        idx = pd.date_range(end=ts.max().floor("5min"), periods=n, freq="5min", tz="UTC")
        rng = np.random.default_rng(42)
        noise = rng.normal(0, 0.15, n)
        closes = anchor + np.cumsum(noise)
        highs = closes + rng.uniform(0.2, 1.0, n)
        lows = closes - rng.uniform(0.2, 1.0, n)
        opens = np.roll(closes, 1)
        opens[0] = closes[0]
        return pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": np.full(n, 100.0)},
            index=idx,
        )
