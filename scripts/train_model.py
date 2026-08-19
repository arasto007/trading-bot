#!/usr/bin/env python3
"""Phase 8.6 production ML training CLI (offline, CPU-only)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.training.trainer import ProductionTrainer

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train baseline ML models on dataset v2")
    parser.add_argument("--symbol", default="XAUUSD", help="Trading symbol")
    parser.add_argument("--timeframe", default="M5", help="Timeframe")
    parser.add_argument("--dataset", default="v2", choices=["v2"], help="Dataset version")
    parser.add_argument(
        "--model",
        default="all",
        help="Model to train (logistic, random_forest, xgboost, lightgbm, all) "
        "or artifact path when using --evaluate",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--base-dir", default=None, help="ML data root override")
    parser.add_argument("--min-samples", type=int, default=500, help="Sanity gate minimum samples")
    parser.add_argument("--version", default=None, help="Explicit model version to write")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted training run")
    parser.add_argument(
        "--phase9-2",
        action="store_true",
        help="Phase 9.2 production training (deep-audit gate, canonical artifacts)",
    )
    parser.add_argument(
        "--phase9-4",
        action="store_true",
        help="Phase 9.4 research-based retraining (experimental datasets only)",
    )
    parser.add_argument(
        "--phase9-5",
        action="store_true",
        help="Phase 9.5 advanced feature & signal discovery (research only)",
    )
    parser.add_argument(
        "--phase9-6",
        action="store_true",
        help="Phase 9.6 regime & robust signal optimization (research only)",
    )
    parser.add_argument(
        "--phase9-8",
        action="store_true",
        help="Phase 9.8 walk-forward validation & robustness testing (research only)",
    )
    parser.add_argument(
        "--phase9-9",
        action="store_true",
        help="Phase 9.9 robustness & overfitting reduction (research only)",
    )
    parser.add_argument(
        "--research-optimize",
        action="store_true",
        help="Phase 9.3 research optimization (analysis only, no retraining)",
    )
    parser.add_argument(
        "--research-skip-slow",
        action="store_true",
        help="Skip hyperparameter grid search in Phase 9.3 (faster)",
    )
    parser.add_argument("--evaluate", action="store_true", help="Evaluate an existing model artifact")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.dataset != "v2":
        logger.error("Only dataset v2 is supported in Phase 8.6")
        return 2

    trainer = ProductionTrainer(
        base_dir=args.base_dir,
        seed=args.seed,
        min_samples=args.min_samples,
        resume=args.resume,
    )

    if args.evaluate:
        if args.model in ("all", "v2"):
            logger.error("--evaluate requires a model artifact path (e.g. model_v1.pkl)")
            return 2
        result = trainer.evaluate_existing(args.model, args.symbol, args.timeframe)
        print(json.dumps(result, indent=2))
        return 0

    if args.phase9_2:
        from tradingbot.ml.training.phase9_production import Phase92ProductionTrainer

        trainer92 = Phase92ProductionTrainer(
            base_dir=args.base_dir,
            seed=args.seed,
            min_samples=args.min_samples,
        )
        result = trainer92.run(args.symbol, args.timeframe, version=args.version)
        print(json.dumps(result.to_dict(), indent=2))
        if result.blocked:
            logger.error("Phase 9.2 training blocked: %s", result.block_reason)
            return 1
        logger.info("Phase 9.2 training complete. Report: %s", result.report_path)
        return 0

    if args.research_optimize:
        from tradingbot.ml.research.research_orchestrator import MLResearchOptimizer

        optimizer = MLResearchOptimizer(
            base_dir=args.base_dir,
            seed=args.seed,
            skip_slow=args.research_skip_slow,
        )
        result = optimizer.run(args.symbol, args.timeframe)
        print(json.dumps(result.to_dict(), indent=2))
        if result.blocked:
            logger.error("Phase 9.3 research blocked: %s", result.block_reason)
            return 1
        logger.info("Phase 9.3 research complete. Report: %s", result.report_path)
        return 0

    if args.phase9_4:
        from tradingbot.ml.research.retrain_optimizer import Phase94RetrainOptimizer

        optimizer94 = Phase94RetrainOptimizer(base_dir=args.base_dir, seed=args.seed)
        result = optimizer94.run(args.symbol, args.timeframe)
        print(json.dumps(result.to_dict(), indent=2))
        if result.blocked:
            logger.error("Phase 9.4 retraining blocked: %s", result.block_reason)
            return 1
        if not result.improved_over_baseline:
            logger.warning("Phase 9.4 complete but validation ROC-AUC did not beat Phase 9.2 baseline")
        logger.info("Phase 9.4 retraining complete. Report: %s", result.report_path)
        return 0

    if args.phase9_5:
        from tradingbot.ml.research.advanced_discovery.experiment_runner import AdvancedDiscoveryRunner

        runner = AdvancedDiscoveryRunner(base_dir=args.base_dir, seed=args.seed)
        result = runner.run(args.symbol, args.timeframe)
        print(json.dumps(result.to_dict(), indent=2))
        if result.blocked:
            logger.error("Phase 9.5 discovery blocked: %s", result.block_reason)
            return 1
        logger.info("Phase 9.5 discovery complete. Report: %s", result.report_path)
        logger.info("Recommendation: %s", result.recommendation)
        return 0

    if args.phase9_6:
        from tradingbot.ml.research.regime_optimization import RegimeOptimizationOrchestrator

        orchestrator = RegimeOptimizationOrchestrator(base_dir=args.base_dir, seed=args.seed)
        result = orchestrator.run(args.symbol, args.timeframe)
        print(json.dumps(result.to_dict(), indent=2))
        if result.blocked:
            logger.error("Phase 9.6 optimization blocked: %s", result.block_reason)
            return 1
        logger.info("Phase 9.6 optimization complete. Report: %s", result.report_path)
        logger.info("Recommendation: %s", result.recommendation)
        return 0

    if args.phase9_8:
        from tradingbot.ml.research.walk_forward import WalkForwardEngine

        engine = WalkForwardEngine(base_dir=args.base_dir, seed=args.seed)
        result = engine.run(args.symbol, args.timeframe)
        print(json.dumps(result.to_dict(), indent=2))
        if result.blocked:
            logger.error("Phase 9.8 walk-forward blocked: %s", result.block_reason)
            return 1
        logger.info("Phase 9.8 complete. Decision: %s", result.final_decision)
        return 0 if result.final_verdict == "PASS" else 1

    if args.phase9_9:
        from tradingbot.ml.research.robustness_optimizer import RobustnessOptimizer

        optimizer = RobustnessOptimizer(base_dir=args.base_dir, seed=args.seed)
        result = optimizer.run(args.symbol, args.timeframe)
        print(json.dumps(result.to_dict(), indent=2))
        if result.blocked:
            logger.error("Phase 9.9 blocked: %s", result.block_reason)
            return 1
        logger.info("Phase 9.9 complete. Verdict: %s", result.final_verdict)
        return 0 if result.final_verdict == "PASS" else 1

    result = trainer.run(
        args.symbol,
        args.timeframe,
        model=args.model,
        version=args.version,
    )
    print(json.dumps(result.to_dict(), indent=2))
    if result.blocked:
        logger.error("Training blocked: %s", result.block_reason)
        return 1
    logger.info("Training complete. Report: %s", result.report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
