"""Phase 10.4 — real-time shadow run monitor."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import ml_shadow_monitor_checkpoint_path
from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.monitoring.performance_tracker import PerformanceTracker

logger = logging.getLogger(__name__)
MONITOR_FEATURES = ("ema50_slope", "candle_direction", "structure_distance")


class ShadowMonitor:
    """Collect per-cycle metrics during a live shadow run."""

    def __init__(
        self,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        risk_percent: float = 0.005,
        base_dir: str | Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.risk_percent = risk_percent
        self.base_dir = base_dir
        self.performance = PerformanceTracker()
        self.candles: pd.DataFrame | None = None
        self._feature_builder: FeatureBuilder | None = None

        self.candles_processed = 0
        self.kernel_cycles = 0
        self.pipeline_errors = 0
        self.risk_block_log_count = 0
        self.ml_buy = 0
        self.ml_sell = 0
        self.ml_hold = 0
        self.kernel_accepted = 0
        self.kernel_rejected = 0
        self.risk_allowed = 0
        self.risk_blocked = 0
        self.risk_reasons: dict[str, int] = {}
        self.execution_blocked = 0
        self.invalid_trades: list[dict[str, Any]] = []
        self.trade_quality: list[dict[str, Any]] = []
        self.probabilities: list[float] = []
        self.feature_samples: dict[str, list[float]] = {k: [] for k in MONITOR_FEATURES}
        self.last_bar_index = -1
        self.started_at = datetime.now(timezone.utc)

    def attach_candles(self, candles: pd.DataFrame) -> None:
        self.candles = candles
        if self._feature_builder is None:
            self._feature_builder = FeatureBuilder(self.symbol, self.base_dir)

    def _hour_key(self, timestamp: str) -> str:
        try:
            ts = pd.Timestamp(timestamp)
            return ts.floor("h").isoformat()
        except Exception:
            return timestamp[:13]

    def on_cycle(
        self,
        *,
        event: dict[str, Any],
        context: dict[str, Any],
        ml_meta: dict[str, Any],
        bar_index: int,
        pipeline_errors: list[str] | None = None,
        risk_blocks: list[str] | None = None,
        trade_quality: dict[str, Any] | None = None,
        invalid_trade: dict[str, Any] | None = None,
    ) -> None:
        self.kernel_cycles += 1
        self.candles_processed += 1
        self.last_bar_index = bar_index
        hour = self._hour_key(str(event.get("timestamp", "")))

        bucket = self.performance.state.hourly_buckets.setdefault(
            hour,
            {"cycles": 0, "ml_buy": 0, "ml_sell": 0, "ml_hold": 0, "risk_allowed": 0, "trades_closed": 0},
        )
        bucket["cycles"] += 1

        ml_dir = str(ml_meta.get("ml_direction", event.get("ml_signal", "HOLD"))).upper()
        if ml_dir == "BUY":
            self.ml_buy += 1
            bucket["ml_buy"] += 1
        elif ml_dir == "SELL":
            self.ml_sell += 1
            bucket["ml_sell"] += 1
        else:
            self.ml_hold += 1
            bucket["ml_hold"] += 1

        prob = event.get("ml_probability") or ml_meta.get("ml_probability")
        if prob is not None:
            self.probabilities.append(float(prob))

        if context.get("has_signal"):
            self.kernel_accepted += 1
        else:
            self.kernel_rejected += 1

        if event.get("risk_allowed") is True:
            self.risk_allowed += 1
            bucket["risk_allowed"] += 1
        elif event.get("risk_allowed") is False:
            self.risk_blocked += 1
            reason = str(event.get("risk_reason") or "unknown").split("(")[0].strip().lower()
            if "spread" in reason:
                key = "spread"
            elif "atr" in reason or "volatility" in reason:
                key = "volatility"
            elif "friday" in reason or "session" in reason:
                key = "session"
            elif "position" in reason or "risk" in reason:
                key = "risk_limit"
            else:
                key = reason or "other"
            self.risk_reasons[key] = self.risk_reasons.get(key, 0) + 1

        if event.get("execution_status") and "shadow_blocked" in str(event.get("execution_status")):
            self.execution_blocked += 1

        real_errors = (
            pipeline_errors
            if pipeline_errors is not None
            else list(context.get("pipeline_errors") or [])
        )
        blocks = risk_blocks if risk_blocks is not None else list(context.get("risk_blocks") or [])
        if real_errors:
            self.pipeline_errors += len(real_errors)
        if blocks:
            self.risk_block_log_count += len(blocks)

        if invalid_trade is not None:
            self.invalid_trades.append(invalid_trade)

        if trade_quality is not None:
            self.trade_quality.append(trade_quality)
            self.performance.on_virtual_entry(hour)

        self._sample_features(bar_index)

    def _sample_features(self, bar_index: int) -> None:
        if self.candles is None or self._feature_builder is None:
            return
        if bar_index < 60 or bar_index >= len(self.candles):
            return
        try:
            feats = self._feature_builder.compute_at(self.candles, bar_index)
            for name in MONITOR_FEATURES:
                if name in feats:
                    self.feature_samples[name].append(float(feats[name]))
        except Exception as exc:
            logger.debug("Feature sample skipped: %s", exc)

    def on_trade_close(self, trade: dict[str, Any]) -> None:
        hour = self._hour_key(str(trade.get("timestamp", "")))
        self.performance.on_trade_close(trade, hour_key=hour)

    def on_equity(self, point: dict[str, Any]) -> None:
        self.performance.on_equity(point)

    def save_checkpoint(self) -> None:
        path = ml_shadow_monitor_checkpoint_path(self.run_id, self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": self.run_id,
            "last_bar_index": self.last_bar_index,
            "kernel_cycles": self.kernel_cycles,
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def load_checkpoint(run_id: str, base_dir: str | Path | None = None) -> dict[str, Any] | None:
        path = ml_shadow_monitor_checkpoint_path(run_id, base_dir)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def signals_summary(self) -> dict[str, Any]:
        total = self.ml_buy + self.ml_sell + self.ml_hold
        probs = self.probabilities
        return {
            "candles_processed": self.candles_processed,
            "ml_predictions": total,
            "ml_buy": self.ml_buy,
            "ml_sell": self.ml_sell,
            "ml_hold": self.ml_hold,
            "hold_pct": round(self.ml_hold / total, 4) if total else 0.0,
            "probability_mean": round(sum(probs) / len(probs), 4) if probs else None,
            "probability_std": round(float(pd.Series(probs).std()), 4) if len(probs) > 1 else None,
            "kernel_accepted": self.kernel_accepted,
            "kernel_rejected": self.kernel_rejected,
            "pipeline_errors": self.pipeline_errors,
            "risk_block_log_count": self.risk_block_log_count,
        }

    def risk_summary(self) -> dict[str, Any]:
        total = self.risk_allowed + self.risk_blocked
        return {
            "risk_allowed": self.risk_allowed,
            "risk_blocked": self.risk_blocked,
            "allow_ratio": round(self.risk_allowed / total, 4) if total else 0.0,
            "block_reasons": dict(self.risk_reasons),
            "execution_blocked": self.execution_blocked,
        }
