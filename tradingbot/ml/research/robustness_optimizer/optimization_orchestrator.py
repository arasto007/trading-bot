"""Phase 9.9 — robustness & overfitting reduction orchestrator."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.ml.backtest.model_loader import load_phase9_6_bundle, verify_integrity
from tradingbot.ml.data.paths import phase9_8_robustness_report_path, phase9_8_walk_forward_report_path
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.robustness_optimizer.candidate_selector import (
    PRODUCTION_WINNER_RULE,
    rank_candidates,
    select_production_winner,
)
from tradingbot.ml.research.robustness_optimizer.freeze_bridge import (
    FreezeBridgeError,
    build_freeze_contract,
)
from tradingbot.ml.research.robustness_optimizer.model_regularization import build_regularized_candidates
from tradingbot.ml.research.robustness_optimizer.regime_robustness import analyze_regime_robustness
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance, save_reports
from tradingbot.ml.research.robustness_optimizer.stable_feature_research import run_feature_selection_research
from tradingbot.ml.research.robustness_optimizer.walk_forward_optimizer import run_candidate_grid
from tradingbot.ml.research.walk_forward.window_manager import assert_chronological
from tradingbot.ml.training.data_loader import filter_resolved_labels
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)
PHASE = "9.9"


@dataclass
class RobustnessOptimizationResult:
    symbol: str
    timeframe: str
    status: str
    final_verdict: str
    robustness_score: float
    overfitting_risk: str
    report_paths: dict[str, str] = field(default_factory=dict)
    best_candidate: dict[str, Any] = field(default_factory=dict)
    acceptance: dict[str, Any] = field(default_factory=dict)
    freeze_contract: dict[str, Any] = field(default_factory=dict)
    freeze_manifest_path: str = ""
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "final_verdict": self.final_verdict,
            "robustness_score": self.robustness_score,
            "overfitting_risk": self.overfitting_risk,
            "report_paths": self.report_paths,
            "best_candidate": self.best_candidate,
            "acceptance": self.acceptance,
            "freeze_contract": self.freeze_contract,
            "freeze_manifest_path": self.freeze_manifest_path,
            "production_winner_rule": PRODUCTION_WINNER_RULE,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


def _load_phase98_baseline(base_dir: str | Path | None) -> dict[str, Any]:
    path = phase9_8_walk_forward_report_path(base_dir)
    if not path.is_file():
        return {"robustness_score": 0.0, "overfitting_risk": "HIGH"}
    report = json.loads(path.read_text(encoding="utf-8"))
    mean_auc_gap = None
    robustness_path = phase9_8_robustness_report_path(base_dir)
    if robustness_path.is_file():
        robustness = json.loads(robustness_path.read_text(encoding="utf-8"))
        train_test_gap = robustness.get("train_test_gap") or {}
        raw_gap = train_test_gap.get("mean_auc_gap")
        if raw_gap is not None:
            mean_auc_gap = float(raw_gap)
    return {
        "robustness_score": float(report.get("robustness_score", 0.0) or 0.0),
        "overfitting_risk": str(report.get("overfitting_risk", "HIGH")),
        "mean_profit_factor": report.get("mean_metrics", {}).get("profit_factor"),
        "mean_expectancy": report.get("mean_metrics", {}).get("expectancy"),
        "mean_auc_gap": mean_auc_gap,
        "source": str(path),
        "mean_auc_gap_source": str(robustness_path) if mean_auc_gap is not None else None,
    }


class RobustnessOptimizer:
    """Phase 9.9 research orchestrator — isolated from production pipelines."""

    def __init__(self, *, base_dir: str | Path | None = None, seed: int = DEFAULT_SEED) -> None:
        self.base_dir = base_dir
        self.seed = seed

    def run(self, symbol: str, timeframe: str, *, freeze_on_pass: bool = True) -> RobustnessOptimizationResult:
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

        baseline = _load_phase98_baseline(self.base_dir)
        feature_research = run_feature_selection_research(self.base_dir)
        feature_subsets = feature_research.get("feature_subsets", {})
        if not feature_subsets:
            feature_subsets = {"stable_default": list(bundle.feature_order)}

        regime_analysis = analyze_regime_robustness(resolved)
        recommended_regime = regime_analysis.get("recommended_filter_regime", "RANGE")

        candidates = build_regularized_candidates(bundle.metadata.get("hyperparameters", {}))
        regimes = [recommended_regime]
        if recommended_regime != "RANGE":
            regimes.append("RANGE")

        logger.info("Phase 9.9: running %s candidates × %s feature sets", len(candidates), len(feature_subsets))
        experiments = run_candidate_grid(
            resolved,
            candidates,
            feature_subsets,
            regimes=regimes,
            seed=self.seed,
        )
        ranked = rank_candidates(experiments)
        experiments_by_id = {
            str(exp.get("experiment_id")): exp for exp in experiments if exp.get("experiment_id")
        }

        production_winner = select_production_winner(ranked, baseline) or {}
        acceptance = evaluate_acceptance(production_winner, baseline) if production_winner else {
            "final_verdict": "FAIL",
            "checks": {},
        }

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

        paths = save_reports(
            symbol=symbol,
            timeframe=timeframe,
            seed=self.seed,
            feature_research=feature_research,
            regime_analysis=regime_analysis,
            ranked=ranked,
            best=production_winner or None,
            acceptance=acceptance,
            baseline=baseline,
            integrity=integrity_payload,
            experiments=experiments,
            base_dir=self.base_dir,
        )

        freeze_contract: dict[str, Any] = {}
        freeze_manifest_path = ""
        if freeze_on_pass and acceptance.get("final_verdict") == "PASS" and production_winner:
            from tradingbot.ml.paper_trading.model_registry import (
                FreezeContractRequiredError,
                freeze_phase9_9_artifacts,
            )

            try:
                freeze_contract = build_freeze_contract(
                    production_winner,
                    acceptance,
                    feature_subsets=feature_subsets,
                    experiment=experiments_by_id.get(str(production_winner.get("experiment_id"))),
                    dataset_fingerprint=fingerprint_before,
                    report_path=str(paths["robustness_report"]),
                )
                freeze_phase9_9_artifacts(
                    raw,
                    contract=freeze_contract,
                    base_dir=self.base_dir,
                    seed=self.seed,
                    report_path=str(paths["robustness_report"]),
                )
                from tradingbot.ml.data.paths import phase9_9_freeze_manifest_path

                freeze_manifest_path = str(phase9_9_freeze_manifest_path(self.base_dir))
                logger.info("Phase 9.9 freeze completed for %s", production_winner.get("experiment_id"))
            except (FreezeBridgeError, FreezeContractRequiredError) as exc:
                logger.warning("Phase 9.9 freeze blocked: %s", exc)
                acceptance = {
                    **acceptance,
                    "final_verdict": "FAIL",
                    "freeze_error": str(exc),
                }

        return RobustnessOptimizationResult(
            symbol=symbol,
            timeframe=timeframe,
            status="PASS" if acceptance.get("final_verdict") == "PASS" else "FAIL",
            final_verdict=str(acceptance.get("final_verdict", "FAIL")),
            robustness_score=float(production_winner.get("robustness_score", 0.0) or 0.0),
            overfitting_risk=str(production_winner.get("overfitting_risk", "HIGH")),
            report_paths={k: str(v) for k, v in paths.items()},
            best_candidate=production_winner,
            acceptance=acceptance,
            freeze_contract=freeze_contract,
            freeze_manifest_path=freeze_manifest_path,
        )

    def _blocked(self, symbol: str, timeframe: str, reason: str) -> RobustnessOptimizationResult:
        logger.warning("Phase 9.9 blocked: %s", reason)
        return RobustnessOptimizationResult(
            symbol=symbol,
            timeframe=timeframe,
            status="FAIL",
            final_verdict="FAIL",
            robustness_score=0.0,
            overfitting_risk="HIGH",
            blocked=True,
            block_reason=reason,
        )
