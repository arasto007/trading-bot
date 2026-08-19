"""Phase 15E — shadow signal failure diagnosis orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.domain.models import MarketKey
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15e_debug.confidence_analysis import ConfidenceAnalyzer
from tradingbot.ml.phase15e_debug.config import DEFAULT_STRIDE, DEFAULT_WARMUP_BARS, reports_dir
from tradingbot.ml.phase15e_debug.legacy_diff import LegacyDiffEngine
from tradingbot.ml.phase15e_debug.regime_analysis import RegimeActivationAnalyzer
from tradingbot.ml.phase15e_debug.report_generator import write_phase15e_reports
from tradingbot.ml.phase15e_debug.root_cause import build_shadow_activation_report, classify_root_cause
from tradingbot.ml.phase15e_debug.signal_funnel import SignalFunnel
from tradingbot.ml.phase15e_debug.stage_probe import probe_bar
from tradingbot.ml.research.phase14_7.config import DEFAULT_QUALITY_THRESHOLD
from tradingbot.ml.trade_quality.quality_policy import QUALITY_THRESHOLD


def _filter_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    if candles.empty:
        return candles
    end = candles.index.max()
    start = end - timedelta(days=days)
    return candles[candles.index >= start]


@dataclass
class Phase15EDebugResult:
    status: str
    primary_cause: str
    reports_dir: str
    funnel: SignalFunnel
    root_cause: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15E",
            "status": self.status,
            "primary_cause": self.primary_cause,
            "reports_dir": self.reports_dir,
            "funnel": self.funnel.build_report(),
            "root_cause": self.root_cause,
        }


def run_phase15e_shadow_debug(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP_BARS,
    legacy_config: dict[str, Any] | None = None,
) -> Phase15EDebugResult:
    PipelineCache.reset()
    cfg = dict(legacy_config or {})
    if base_dir:
        cfg["BASE_DIR"] = str(base_dir)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"candles_unavailable:{symbol}:{timeframe}")

    window = _filter_days(candles, days)
    full_candles = candles
    market = MarketKey(symbol, timeframe)

    stack = build_ml_kernel_stack(base_dir=str(base_dir) if base_dir else None, symbol=symbol)
    adapter = build_kernel_adapter(
        base_dir=str(base_dir) if base_dir else None,
        symbol=symbol,
        stack=stack,
        enable_monitoring=False,
    )
    legacy = LegacyStrategyRegistry(cfg)

    funnel = SignalFunnel()
    regime_analyzer = RegimeActivationAnalyzer()
    confidence_analyzer = ConfidenceAnalyzer()
    legacy_diff = LegacyDiffEngine()

    indices = list(range(warmup, len(window), stride))
    for i in indices:
        bar_ts = window.index[i]
        full_idx = full_candles.index.get_loc(bar_ts)
        slice_df = full_candles.iloc[max(0, full_idx - warmup) : full_idx + 1]

        legacy_signal = None
        try:
            legacy_signal = legacy.generate_signal(market, slice_df.copy())
        except Exception:
            pass

        probe = probe_bar(
            market=market,
            slice_df=slice_df,
            stack=stack,
            adapter=adapter,
            legacy_signal=legacy_signal,
            config=cfg,
            base_dir=str(base_dir) if base_dir else None,
        )
        funnel.add(probe)
        regime_analyzer.probes.append(probe)
        confidence_analyzer.probes.append(probe)
        legacy_diff.probes.append(probe)

    root = classify_root_cause(funnel, regime_analyzer, confidence_analyzer, legacy_diff)
    activation = build_shadow_activation_report(funnel, root)
    funnel_report = funnel.build_report()
    regime_report = regime_analyzer.build_report()
    confidence_report = confidence_analyzer.build_report()
    legacy_report = legacy_diff.build_report()

    ml_signals = funnel_report["stage_summary"].get("trading_signal_buy_sell", 0)
    final_report = {
        "phase": "15E",
        "shadow_mode_issue": ml_signals == 0 and funnel_report.get("legacy_signals", 0) > 0,
        "primary_bottleneck": root.get("primary_cause", ""),
        "stage_failing": root.get("stage_failing", ""),
        "fix_recommendation": root.get("fix_recommendation", ""),
        "safe_to_enable_ml_live": root.get("safe_to_enable_ml_live", False),
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "seed": seed,
        "stride": stride,
        "warmup": warmup,
        "thresholds_in_use": {
            "calibration_min": 0.55,
            "quality_factory": DEFAULT_QUALITY_THRESHOLD,
            "quality_policy_spec": QUALITY_THRESHOLD,
        },
        "activation": activation,
        "funnel_summary": funnel_report.get("stage_summary", {}),
        "regime_distribution": regime_report.get("regime_distribution", {}),
    }

    out = write_phase15e_reports(
        funnel_report=funnel_report,
        activation_report=activation,
        regime_report=regime_report,
        confidence_report=confidence_report,
        legacy_diff_report=legacy_report,
        root_cause_report=root,
        final_report=final_report,
        base_dir=base_dir,
    )

    status = "DIAGNOSED" if final_report["shadow_mode_issue"] else "OK"
    return Phase15EDebugResult(
        status=status,
        primary_cause=str(root.get("primary_cause", "")),
        reports_dir=str(out),
        funnel=funnel,
        root_cause=root,
    )
