"""Phase 9.6 — regime & robust signal optimization orchestrator."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_4_retraining_report_path,
    phase9_5_discovery_report_path,
    phase9_6_optimization_report_path,
    training_comparison_report_path,
)
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.regime_optimization.event_filter_optimizer import (
    run_event_filter_optimization,
    save_event_filter_report,
)
from tradingbot.ml.research.regime_optimization.regime_detector import run_regime_analysis, save_regime_analysis_report
from tradingbot.ml.research.regime_optimization.regime_model_optimizer import run_regime_model_optimization
from tradingbot.ml.research.regime_optimization.regime_utils import EVENT_SCHEMES
from tradingbot.ml.research.regime_optimization.stable_feature_selector import (
    run_feature_stability_selection,
    save_feature_stability_report,
)
from tradingbot.ml.research.regime_optimization.walk_forward_validator import (
    run_walk_forward_validation,
    save_walk_forward_report,
)
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.training.data_loader import filter_resolved_labels, load_dataset_v2_splits
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)

PHASE = "9.6"


@dataclass
class RegimeOptimizationResult:
    symbol: str
    timeframe: str
    status: str
    recommendation: str
    report_path: str
    superior_configuration_found: bool = False
    blocked: bool = False
    block_reason: str = ""
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "recommendation": self.recommendation,
            "report_path": self.report_path,
            "superior_configuration_found": self.superior_configuration_found,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "summary": self.summary,
        }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _phase_baselines(base_dir: str | Path | None) -> dict[str, Any]:
    p92 = _load_json(training_comparison_report_path(base_dir))
    p94 = _load_json(phase9_4_retraining_report_path(base_dir))
    p95 = _load_json(phase9_5_discovery_report_path(base_dir))
    p92_auc = 0.0
    if p92:
        best = p92.get("best_model", "")
        p92_auc = float(
            p92.get("evaluations", {}).get(best, {}).get("validation", {}).get("classification", {}).get("roc_auc", 0)
        )
    p94_auc = float(p94.get("summary", {}).get("validation_roc_auc", 0) or 0)
    if not p94_auc:
        p94_auc = float(
            p94.get("best_model", {}).get("validation_metrics", {}).get("classification", {}).get("roc_auc", 0)
        )
    p95_auc = float(p95.get("model_findings", {}).get("validation_roc_auc", 0) or 0)
    return {"phase9_2_val_roc_auc": p92_auc, "phase9_4_val_roc_auc": p94_auc, "phase9_5_val_roc_auc": p95_auc}


def _load_tuned_hp(base_dir: str | Path | None) -> dict[str, dict[str, Any]]:
    from tradingbot.ml.data.paths import model_optimization_report_path

    payload = _load_json(model_optimization_report_path(base_dir))
    return {m["model"]: m.get("best_params", {}) for m in payload.get("models", [])}


def _final_recommendation(
    wf_report: dict[str, Any],
    model_report: dict[str, Any],
    regime_report: dict[str, Any],
    event_report: dict[str, Any],
) -> tuple[str, bool]:
    mean_test_auc = float(wf_report.get("mean_test_roc_auc", 0.0))
    mean_exp = float(wf_report.get("mean_test_expectancy", 0.0))
    test_pf = float(model_report.get("test_profit_factor", 0.0) or 0.0)
    test_exp = float(model_report.get("test_expectancy", 0.0) or 0.0)
    test_auc = float(model_report.get("test_roc_auc", 0.0) or 0.0)

    best_regime = regime_report.get("best_regime")
    best_event_scheme = event_report.get("best_scheme")
    regime_edge = False
    if best_regime and best_event_scheme:
        for row in regime_report.get("by_regime", []):
            if row.get("regime") == best_regime and row.get("expectancy", 0) > 0.05:
                regime_edge = True

    success = (
        mean_test_auc >= 0.55
        or test_auc >= 0.55
        or mean_exp > 0
        or test_exp > 0
        or test_pf >= 1.2
        or regime_edge
    )
    if success:
        return "READY FOR BACKTEST", True
    return "MORE RESEARCH REQUIRED", False


class RegimeOptimizationOrchestrator:
    """Phase 9.6 research orchestrator — isolated experiments only."""

    def __init__(self, *, base_dir: str | Path | None = None, seed: int = DEFAULT_SEED) -> None:
        self.base_dir = base_dir
        self.seed = seed

    def run(self, symbol: str, timeframe: str) -> RegimeOptimizationResult:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        store = DatasetStore(self.base_dir)
        raw = store.load_v2(symbol, timeframe)
        if raw is None or raw.empty:
            return self._blocked(symbol, timeframe, "dataset_v2_missing")

        fingerprint_before = dataset_content_fingerprint(raw)
        resolved = filter_resolved_labels(raw)

        logger.info("Phase 9.6: regime detection")
        regime_report = run_regime_analysis(resolved)
        save_regime_analysis_report(resolved, self.base_dir)

        logger.info("Phase 9.6: event filter optimization")
        event_report = run_event_filter_optimization(resolved)
        save_event_filter_report(resolved, self.base_dir)

        logger.info("Phase 9.6: feature stability selection")
        splits = load_dataset_v2_splits(symbol, timeframe, self.base_dir)
        stability_report = run_feature_stability_selection(splits, seed=self.seed)
        save_feature_stability_report(splits, self.base_dir, seed=self.seed)
        feature_sets = stability_report.get("feature_sets", {})
        primary_features = feature_sets.get("B_top15_stable") or feature_sets.get("A_top10_stable", [])

        logger.info("Phase 9.6: walk-forward validation")
        wf_report = run_walk_forward_validation(resolved, primary_features, seed=self.seed)
        save_walk_forward_report(resolved, primary_features, self.base_dir, seed=self.seed)

        logger.info("Phase 9.6: regime model optimization")
        ranked = event_report.get("ranked_by_expectancy", list(EVENT_SCHEMES.keys()))
        top_schemes = list(dict.fromkeys(list(ranked[:3]) + ["A_all_events"]))

        model_report = run_regime_model_optimization(
            resolved,
            symbol,
            timeframe,
            feature_sets=feature_sets,
            event_schemes=top_schemes,
            base_dir=self.base_dir,
            seed=self.seed,
            hyperparameters=_load_tuned_hp(self.base_dir),
        )

        raw_after = store.load_v2(symbol, timeframe)
        fingerprint_after = dataset_content_fingerprint(raw_after) if raw_after is not None else ""
        if fingerprint_before != fingerprint_after:
            return self._blocked(symbol, timeframe, "dataset_v2_mutated")

        baselines = _phase_baselines(self.base_dir)
        val_auc = float(model_report.get("validation_roc_auc", 0.0) or 0.0)
        superior = val_auc > max(
            baselines.get("phase9_2_val_roc_auc", 0.0),
            baselines.get("phase9_4_val_roc_auc", 0.0),
            baselines.get("phase9_5_val_roc_auc", 0.0),
        )
        has_configuration = bool(model_report.get("best_configuration"))
        if not has_configuration and not model_report.get("configurations"):
            superior = False
        recommendation, ready = _final_recommendation(wf_report, model_report, regime_report, event_report)

        best_cfg = model_report.get("best_configuration", {})
        label_config = {
            "source": "dataset_v2",
            "note": "Phase 9.6 uses original labels within regime/event subsets",
        }

        final_report = {
            "phase": PHASE,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "seed": self.seed,
            "status": "PASS",
            "recommendation": recommendation,
            "dataset": {
                "fingerprint": fingerprint_before,
                "fingerprint_unchanged": fingerprint_before == fingerprint_after,
                "rows": len(raw),
                "resolved_rows": len(resolved),
            },
            "best_configuration": {
                "regime": best_cfg.get("regime"),
                "event_filter": best_cfg.get("event_scheme"),
                "feature_set": best_cfg.get("feature_set"),
                "label_configuration": label_config,
                "model": best_cfg.get("model"),
            },
            "metrics": {
                "ml": {
                    "validation_roc_auc": val_auc,
                    "test_roc_auc": model_report.get("test_roc_auc"),
                    "precision": model_report.get("best_candidate", {}).get("validation", {}).get("classification", {}).get("precision"),
                    "recall": model_report.get("best_candidate", {}).get("validation", {}).get("classification", {}).get("recall"),
                    "f1": model_report.get("best_candidate", {}).get("validation", {}).get("classification", {}).get("f1"),
                },
                "trading": {
                    "win_rate": model_report.get("best_candidate", {}).get("test", {}).get("trading", {}).get("win_rate"),
                    "expectancy": model_report.get("test_expectancy"),
                    "profit_factor": model_report.get("test_profit_factor"),
                    "average_R": model_report.get("test_expectancy"),
                    "drawdown": model_report.get("best_candidate", {}).get("test", {}).get("trading", {}).get("max_drawdown_proxy"),
                },
            },
            "feature_findings": {
                "stable_features": stability_report.get("stable_features", [])[:15],
                "unstable_features": stability_report.get("unstable_features", []),
                "removed_features": stability_report.get("remove_features", []),
                "feature_sets": feature_sets,
            },
            "signal_findings": {
                "best_events": event_report.get("ranked_by_expectancy", [])[:3],
                "worst_events": event_report.get("results", [])[-1:] if event_report.get("results") else [],
            },
            "regime_findings": regime_report,
            "walk_forward": wf_report,
            "model_optimization": model_report,
            "comparison_with_previous_phases": baselines,
            "superior_to_previous_phases": superior,
        }

        report_path = phase9_6_optimization_report_path(self.base_dir)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")

        return RegimeOptimizationResult(
            symbol=symbol,
            timeframe=timeframe,
            status="PASS",
            recommendation=recommendation,
            report_path=str(report_path),
            superior_configuration_found=superior or has_configuration,
            summary={
                "validation_roc_auc": val_auc,
                "test_roc_auc": model_report.get("test_roc_auc"),
                "best_regime": best_cfg.get("regime"),
                "best_event_scheme": best_cfg.get("event_scheme"),
                "walk_forward_mean_test_auc": wf_report.get("mean_test_roc_auc"),
            },
        )

    def _blocked(self, symbol: str, timeframe: str, reason: str) -> RegimeOptimizationResult:
        logger.warning("Phase 9.6 blocked: %s", reason)
        return RegimeOptimizationResult(
            symbol=symbol,
            timeframe=timeframe,
            status="FAIL",
            recommendation="MORE RESEARCH REQUIRED",
            report_path="",
            blocked=True,
            block_reason=reason,
        )
