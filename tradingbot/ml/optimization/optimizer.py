"""Shadow policy optimizer — learns from decision + outcome memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.optimization._sim import metrics_from_r, trade_r_values
from tradingbot.ml.optimization.filters import AdaptiveFilterAnalyzer
from tradingbot.ml.optimization.recommendation import build_recommendation_payload
from tradingbot.ml.optimization.reports import write_shadow_optimization_report
from tradingbot.ml.optimization.schema import OptimizationResult, PolicyConfig, utc_now_iso
from tradingbot.ml.optimization.threshold import ThresholdOptimizer
from tradingbot.ml.optimization.weights import WeightOptimizer


def load_current_policy(base_dir: str | Path | None = None) -> PolicyConfig:
    """Load baseline policy from existing reports (no live changes)."""
    cfg = PolicyConfig()
    path = reports_dir(base_dir) / "optimal_threshold.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg.threshold = float(data.get("best_threshold", cfg.threshold))
    opt_path = reports_dir(base_dir) / "shadow_optimization.json"
    if opt_path.is_file():
        prev = json.loads(opt_path.read_text(encoding="utf-8"))
        rec = prev.get("recommended_config") or prev
        if "ml_weight" in rec:
            cfg.ml_weight = float(rec.get("ml_weight", cfg.ml_weight))
            cfg.rule_weight = float(rec.get("rule_weight", cfg.rule_weight))
    return cfg.normalized()


class ShadowPolicyOptimizer:
    """
    Offline optimizer over shadow memory.

    Produces configuration candidates only — never executes trades.
    """

    def __init__(
        self,
        *,
        min_samples: int = 5,
        base_dir: str | Path | None = None,
    ) -> None:
        self.min_samples = min_samples
        self.base_dir = base_dir

    def optimize(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
        *,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
        current: PolicyConfig | None = None,
    ) -> OptimizationResult:
        current_cfg = (current or load_current_policy(self.base_dir)).normalized()
        pairs_count = sum(1 for d in decisions if d.decision_id in outcomes)
        warnings: list[str] = []

        if pairs_count < self.min_samples:
            warnings.append(f"insufficient paired samples: {pairs_count}")

        r_before = trade_r_values(
            self._pairs(decisions, outcomes),
            threshold=current_cfg.threshold,
            ml_weight=current_cfg.ml_weight,
            rule_weight=current_cfg.rule_weight,
            min_score=current_cfg.min_score,
            disabled_sessions=set(current_cfg.disabled_sessions),
            disabled_regimes=set(current_cfg.disabled_regimes),
        )
        before_metrics = metrics_from_r(r_before)

        thr_opt = ThresholdOptimizer(
            min_samples=self.min_samples,
            ml_weight=current_cfg.ml_weight,
            rule_weight=current_cfg.rule_weight,
            min_score=current_cfg.min_score,
        )
        best_thr, _, thr_warnings = thr_opt.optimize(decisions, outcomes)
        warnings.extend(thr_warnings)

        thr_value = best_thr.threshold if best_thr else current_cfg.threshold
        w_opt = WeightOptimizer(
            min_samples=self.min_samples,
            threshold=thr_value,
            min_score=current_cfg.min_score,
        )
        best_w, _, w_warnings = w_opt.optimize(decisions, outcomes)
        warnings.extend(w_warnings)

        filters = AdaptiveFilterAnalyzer(min_samples=self.min_samples).analyze(decisions, outcomes)

        recommended = PolicyConfig(
            threshold=thr_value,
            ml_weight=best_w.ml_weight if best_w else current_cfg.ml_weight,
            rule_weight=best_w.rule_weight if best_w else current_cfg.rule_weight,
            min_score=current_cfg.min_score,
            disabled_sessions=list(filters.disabled_sessions),
            disabled_regimes=list(filters.disabled_regimes),
        ).normalized()

        r_after = trade_r_values(
            self._pairs(decisions, outcomes),
            threshold=recommended.threshold,
            ml_weight=recommended.ml_weight,
            rule_weight=recommended.rule_weight,
            min_score=recommended.min_score,
            disabled_sessions=set(recommended.disabled_sessions),
            disabled_regimes=set(recommended.disabled_regimes),
        )
        after_metrics = metrics_from_r(r_after)

        confidence_change = round(after_metrics["win_rate"] - before_metrics["win_rate"], 4)

        return OptimizationResult(
            timestamp=utc_now_iso(),
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            current_config=current_cfg,
            recommended_config=recommended,
            expected_R_before=before_metrics["expected_R"],
            expected_R_after=after_metrics["expected_R"],
            confidence_change=confidence_change,
            sample_size=pairs_count,
            warnings=warnings,
        )

    def optimize_from_store(
        self,
        store: DecisionMemoryStore,
        *,
        timeframe: str = "M5",
    ) -> OptimizationResult:
        return self.optimize(
            store.load_decisions(),
            store.load_outcomes_by_id(),
            symbol=store.symbol,
            timeframe=timeframe,
        )

    def run_and_report(
        self,
        store: DecisionMemoryStore,
        *,
        timeframe: str = "M5",
    ) -> dict[str, Any]:
        result = self.optimize_from_store(store, timeframe=timeframe)

        thr_opt = ThresholdOptimizer(min_samples=self.min_samples)
        best_thr, _, _ = thr_opt.optimize(store.load_decisions(), store.load_outcomes_by_id())
        w_opt = WeightOptimizer(min_samples=self.min_samples, threshold=result.recommended_config.threshold)
        best_w, _, _ = w_opt.optimize(store.load_decisions(), store.load_outcomes_by_id())
        filters = AdaptiveFilterAnalyzer(min_samples=self.min_samples).analyze(
            store.load_decisions(),
            store.load_outcomes_by_id(),
        )

        payload = build_recommendation_payload(
            result,
            threshold_candidate=best_thr,
            weight_candidate=best_w,
            filters=filters,
        )
        write_shadow_optimization_report(payload, self.base_dir)
        return payload

    @staticmethod
    def _pairs(
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> list[tuple[DecisionRecord, OutcomeRecord]]:
        from tradingbot.ml.optimization._sim import iter_pairs

        return iter_pairs(decisions, outcomes)
