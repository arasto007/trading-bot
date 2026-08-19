"""Phase 9.3 — research orchestrator."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    feature_importance_report_path,
    label_experiments_report_path,
    model_optimization_report_path,
    phase9_3_research_report_path,
    sampling_analysis_report_path,
    threshold_analysis_report_path,
)
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.feature_importance_analysis import (
    run_feature_importance_analysis,
    save_feature_importance_report,
)
from tradingbot.ml.research.label_experiment import (
    run_label_experiments,
    save_label_experiments_report,
    select_best_label_configuration,
)
from tradingbot.ml.research.model_optimizer import run_model_optimization, save_model_optimization_report
from tradingbot.ml.research.research_utils import (
    PHASE,
    dataset_content_fingerprint,
    load_research_context,
)
from tradingbot.ml.research.sampling_analysis import run_sampling_analysis, save_sampling_analysis_report
from tradingbot.ml.research.threshold_optimizer import (
    run_threshold_optimization,
    save_threshold_analysis_report,
    select_best_threshold,
)
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)


@dataclass
class ResearchRunResult:
    symbol: str
    timeframe: str
    status: str
    report_path: str
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "report_path": self.report_path,
            "artifacts": self.artifacts,
            "summary": self.summary,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


class MLResearchOptimizer:
    """
    Phase 9.3 research-only optimization layer.

    Does not modify dataset_v2, training pipeline, or production artifacts.
    """

    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        seed: int = DEFAULT_SEED,
        skip_slow: bool = False,
    ) -> None:
        self.base_dir = base_dir
        self.seed = seed
        self.skip_slow = skip_slow

    def run(self, symbol: str, timeframe: str) -> ResearchRunResult:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        store = DatasetStore(self.base_dir)
        raw = store.load_v2(symbol, timeframe)
        if raw is None or raw.empty:
            return ResearchRunResult(
                symbol=symbol,
                timeframe=timeframe,
                status="FAIL",
                report_path="",
                blocked=True,
                block_reason="dataset_v2_missing",
            )

        fingerprint_before = dataset_content_fingerprint(raw)

        try:
            ctx = load_research_context(symbol, timeframe, self.base_dir, seed=self.seed)
        except (FileNotFoundError, ValueError) as exc:
            return ResearchRunResult(
                symbol=symbol,
                timeframe=timeframe,
                status="FAIL",
                report_path="",
                blocked=True,
                block_reason=str(exc),
            )

        logger.info("Phase 9.3: feature importance analysis")
        fi_report = run_feature_importance_analysis(ctx, seed=self.seed)
        fi_path = save_feature_importance_report(ctx, self.base_dir, seed=self.seed)

        logger.info("Phase 9.3: sampling analysis")
        sampling_report = run_sampling_analysis(ctx)
        sampling_path = save_sampling_analysis_report(ctx, self.base_dir)

        logger.info("Phase 9.3: label experiments")
        label_report = run_label_experiments(symbol, timeframe, self.base_dir)
        label_path = label_experiments_report_path(self.base_dir)
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(json.dumps(label_report, indent=2, ensure_ascii=False), encoding="utf-8")

        if self.skip_slow:
            opt_report = {"skipped": True, "best_model": ctx.model_metadata.get("model_name")}
            opt_path = model_optimization_report_path(self.base_dir)
            opt_path.write_text(json.dumps(opt_report, indent=2), encoding="utf-8")
        else:
            logger.info("Phase 9.3: hyperparameter optimization")
            opt_report = run_model_optimization(ctx, seed=self.seed)
            opt_path = save_model_optimization_report(ctx, self.base_dir, seed=self.seed)

        logger.info("Phase 9.3: threshold optimization")
        threshold_report = run_threshold_optimization(ctx)
        threshold_path = save_threshold_analysis_report(ctx, self.base_dir)

        raw_after = store.load_v2(symbol, timeframe)
        fingerprint_after = dataset_content_fingerprint(raw_after) if raw_after is not None else ""
        if fingerprint_before != fingerprint_after:
            return ResearchRunResult(
                symbol=symbol,
                timeframe=timeframe,
                status="FAIL",
                report_path="",
                blocked=True,
                block_reason="dataset_mutation_detected",
            )

        best_features = [r["feature"] for r in fi_report.get("rankings", [])[:10]]
        best_label = select_best_label_configuration(label_report.get("experiments", []))
        best_threshold = select_best_threshold(threshold_report)
        best_model = opt_report.get("best_model") or ctx.model_metadata.get("model_name", "unknown")

        recommendations = _build_recommendations(
            fi_report=fi_report,
            sampling_report=sampling_report,
            label_report=label_report,
            opt_report=opt_report,
            threshold_report=threshold_report,
            production_model=ctx.model_metadata.get("model_name"),
        )

        label_config_str = ""
        if best_label:
            label_config_str = (
                f"ATR{best_label['atr_period']}_TP{best_label['tp_r_multiple']}R_"
                f"window{best_label['future_window_bars']}"
            )

        summary = {
            "status": "PASS",
            "best_model": best_model,
            "best_features": best_features,
            "best_threshold": best_threshold,
            "best_label_configuration": label_config_str,
            "recommendations": recommendations,
            "dataset_fingerprint_unchanged": fingerprint_before == fingerprint_after,
            "production_baseline_model": ctx.model_metadata.get("model_name"),
        }

        final_report = {
            "phase": PHASE,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "seed": self.seed,
            **summary,
            "artifacts": {
                "feature_importance": str(fi_path),
                "sampling_analysis": str(sampling_path),
                "label_experiments": str(label_path),
                "model_optimization": str(opt_path),
                "threshold_analysis": str(threshold_path),
            },
        }

        report_path = phase9_3_research_report_path(self.base_dir)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")

        return ResearchRunResult(
            symbol=symbol,
            timeframe=timeframe,
            status="PASS",
            report_path=str(report_path),
            artifacts=final_report["artifacts"],
            summary=summary,
        )


def _build_recommendations(
    *,
    fi_report: dict[str, Any],
    sampling_report: dict[str, Any],
    label_report: dict[str, Any],
    opt_report: dict[str, Any],
    threshold_report: dict[str, Any],
    production_model: str | None,
) -> list[str]:
    recs: list[str] = []

    dead = fi_report.get("detection", {}).get("dead_features", [])
    low = fi_report.get("detection", {}).get("low_contribution_features", [])
    if dead:
        recs.append(f"Remove or fix {len(dead)} dead/zero-variance features before retraining.")
    if low:
        recs.append(f"Consider dropping {len(low)} low-contribution features in a future experiment.")

    val_auc = opt_report.get("best_validation_roc_auc", 0.0)
    if val_auc < 0.55:
        recs.append(
            "Optimized models still show weak validation ROC-AUC (~0.50); "
            "signal may be near-random with current features and labels."
        )
    else:
        recs.append(f"Hyperparameter tuning improved validation ROC-AUC to {val_auc}.")

    best_label = select_best_label_configuration(label_report.get("experiments", []))
    if best_label:
        recs.append(
            f"Label research: ATR{best_label['atr_period']}, TP{best_label['tp_r_multiple']}R, "
            f"window {best_label['future_window_bars']} bars yields "
            f"{best_label['class_balance_tp_rate']:.1%} TP rate (closest to balance)."
        )

    by_type = sampling_report.get("by_event_type", [])
    if by_type:
        best_event = max(by_type, key=lambda e: e.get("win_rate", 0.0))
        worst_event = min(by_type, key=lambda e: e.get("win_rate", 0.0))
        recs.append(
            f"Event sampling: highest win rate on '{best_event['event_type']}' "
            f"({best_event['win_rate']:.1%}), lowest on '{worst_event['event_type']}' "
            f"({worst_event['win_rate']:.1%})."
        )

    thr = select_best_threshold(threshold_report)
    recs.append(
        f"Raise BUY threshold to {thr:.2f} on validation to trade precision for fewer signals."
    )

    if production_model:
        recs.append(f"Phase 9.2 production model was '{production_model}'; compare with tuned {opt_report.get('best_model')}.")

    if not recs:
        recs.append("No strong signal detected; proceed to backtesting with conservative thresholds only.")

    return recs
