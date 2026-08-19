"""Phase 9.8 — walk-forward validation orchestrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.backtest.model_loader import load_phase9_6_bundle, verify_integrity
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.walk_forward.model_validator import validate_window
from tradingbot.ml.research.walk_forward.report_generator import save_reports
from tradingbot.ml.research.walk_forward.robustness_analyzer import analyze_robustness
from tradingbot.ml.research.walk_forward.walk_forward_metrics import aggregate_window_metrics
from tradingbot.ml.research.walk_forward.window_manager import (
    assert_chronological,
    build_standard_windows,
    partition_window,
)
from tradingbot.ml.training.data_loader import filter_resolved_labels
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)
PHASE = "9.8"


@dataclass
class WalkForwardResult:
    symbol: str
    timeframe: str
    status: str
    final_verdict: str
    final_decision: str
    robustness_score: float
    overfitting_risk: str
    window_count: int
    report_paths: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "final_verdict": self.final_verdict,
            "final_decision": self.final_decision,
            "robustness_score": self.robustness_score,
            "overfitting_risk": self.overfitting_risk,
            "window_count": self.window_count,
            "report_paths": self.report_paths,
            "summary": self.summary,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


class WalkForwardEngine:
    """Offline walk-forward validation for Phase 9.6/9.7 configuration."""

    def __init__(self, *, base_dir: str | None = None, seed: int = DEFAULT_SEED) -> None:
        self.base_dir = base_dir
        self.seed = seed

    def run(self, symbol: str, timeframe: str) -> WalkForwardResult:
        symbol = symbol.upper()
        timeframe = timeframe.upper()
        np.random.seed(self.seed)

        bundle = load_phase9_6_bundle(
            base_dir=self.base_dir,
            build_if_missing=False,
            symbol=symbol,
            timeframe=timeframe,
            seed=self.seed,
        )
        config = bundle.configuration
        regime = config.get("regime", "RANGE")
        event_scheme = config.get("event_filter", "A_all_events")
        model_name = config.get("model", bundle.metadata.get("model_name", "xgboost"))
        hyperparameters = bundle.metadata.get("hyperparameters", {})

        store = DatasetStore(self.base_dir)
        raw = store.load_v2(symbol, timeframe)
        if raw is None or raw.empty:
            return self._blocked(symbol, timeframe, "dataset_v2_missing")

        fingerprint_before = dataset_content_fingerprint(raw)
        integrity = verify_integrity(bundle, raw, expected_fingerprint=bundle.dataset_fingerprint)
        if not integrity.passed:
            return self._blocked(symbol, timeframe, f"integrity_failed: {integrity.errors}")

        resolved = filter_resolved_labels(raw)
        assert_chronological(resolved.sort_values("timestamp"))

        windows = build_standard_windows(resolved)
        if len(windows) < 4:
            logger.warning("Only %s windows available; continuing with adaptive windows", len(windows))

        results: list[dict[str, Any]] = []
        for window in windows:
            train_df, val_df = partition_window(resolved, window)
            logger.info(
                "Phase 9.8 window %s: train=%s val=%s",
                window.window_id,
                len(train_df),
                len(val_df),
            )
            result = validate_window(
                train_df,
                val_df,
                window,
                feature_cols=bundle.feature_order,
                model_name=model_name,
                hyperparameters=hyperparameters,
                seed=self.seed,
                regime=regime,
                event_scheme=event_scheme,
            )
            results.append(result)

        active = [r for r in results if not r.get("skipped")]
        aggregate = aggregate_window_metrics(active)
        robustness = analyze_robustness(active, aggregate)

        raw_after = store.load_v2(symbol, timeframe)
        fp_after = dataset_content_fingerprint(raw_after) if raw_after is not None else ""
        if fingerprint_before != fp_after:
            return self._blocked(symbol, timeframe, "dataset_v2_mutated")

        integrity_payload = {
            "status": integrity.status,
            "checks": integrity.checks,
            "dataset_fingerprint": fingerprint_before,
            "dataset_fingerprint_unchanged": fingerprint_before == fp_after,
        }
        configuration = {
            "regime": regime,
            "event_filter": event_scheme,
            "feature_set": config.get("feature_set", "A_top10_stable"),
            "features": bundle.feature_order,
            "model": model_name,
            "hyperparameters": hyperparameters,
            "risk_pct": 0.005,
            "buy_threshold": 0.55,
            "sell_threshold": 0.45,
            "tp_r": 2.0,
            "sl_r": 1.0,
        }

        paths = save_reports(
            symbol=symbol,
            timeframe=timeframe,
            seed=self.seed,
            windows=results,
            aggregate=aggregate,
            robustness=robustness,
            integrity=integrity_payload,
            configuration=configuration,
            base_dir=self.base_dir,
        )

        final_verdict = "PASS" if len(active) >= 4 and integrity.passed else "FAIL"
        mean_m = aggregate.get("mean_metrics", {})

        return WalkForwardResult(
            symbol=symbol,
            timeframe=timeframe,
            status="PASS" if final_verdict == "PASS" else "FAIL",
            final_verdict=final_verdict,
            final_decision=robustness.get("final_decision", "NEEDS MORE RESEARCH"),
            robustness_score=float(robustness.get("robustness_score", 0.0)),
            overfitting_risk=str(robustness.get("overfitting_risk", "HIGH")),
            window_count=len(active),
            report_paths={k: str(v) for k, v in paths.items()},
            summary={
                "mean_profit_factor": mean_m.get("profit_factor"),
                "mean_expectancy": mean_m.get("expectancy"),
                "mean_win_rate": mean_m.get("win_rate"),
                "worst_window_id": aggregate.get("worst_window", {}).get("window_id"),
                "best_window_id": aggregate.get("best_window", {}).get("window_id"),
            },
        )

    def _blocked(self, symbol: str, timeframe: str, reason: str) -> WalkForwardResult:
        logger.warning("Phase 9.8 blocked: %s", reason)
        return WalkForwardResult(
            symbol=symbol,
            timeframe=timeframe,
            status="FAIL",
            final_verdict="FAIL",
            final_decision="NEEDS MORE RESEARCH",
            robustness_score=0.0,
            overfitting_risk="HIGH",
            window_count=0,
            blocked=True,
            block_reason=reason,
        )
