#!/usr/bin/env python3
"""Phase 8.7 / 9.7 ML backtest CLI (offline, CPU-only)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.backtest.broker_sim import BrokerConfig
from tradingbot.ml.backtest.engine import BacktestConfig, BacktestEngine
from tradingbot.ml.backtest.phase97_engine import Phase97BacktestEngine
from tradingbot.ml.backtest.risk import RiskConfig
from tradingbot.ml.backtest.strategy import StrategyConfig
from tradingbot.ml.data.paths import phase9_7_default_run_id

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ML strategy backtest on dataset v2")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--dataset", default="v2", choices=["v2"])
    parser.add_argument(
        "--phase9-7",
        action="store_true",
        help="Phase 9.7 backtest using Phase 9.6 RANGE+XGBoost research artifacts",
    )
    parser.add_argument("--model", required=False, help="Model artifact path or phase9_6_best")
    parser.add_argument("--split", default="test", help="Dataset split (test, validation, train, all)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--initial-equity", type=float, default=10_000.0)
    parser.add_argument("--buy-threshold", type=float, default=0.55)
    parser.add_argument("--sell-threshold", type=float, default=0.45)
    parser.add_argument("--risk-percent", type=float, default=0.5, help="Risk per trade percent of equity")
    parser.add_argument("--risk-pct", type=float, default=None, help="Risk fraction (overrides --risk-percent)")
    parser.add_argument("--spread", type=float, default=0.30)
    parser.add_argument("--slippage", type=float, default=0.10)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--run", default=None, help="Explicit run id (default phase9_7_v1 for --phase9-7)")
    parser.add_argument("--report-only", action="store_true", help="Load metrics from existing run")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _risk_fraction(args: argparse.Namespace) -> float:
    if args.risk_pct is not None:
        return float(args.risk_pct)
    return float(args.risk_percent) / 100.0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.report_only:
        if not args.run:
            logger.error("--report-only requires --run")
            return 2
        engine = Phase97BacktestEngine(base_dir=args.base_dir) if args.phase9_7 else BacktestEngine(base_dir=args.base_dir)
        report = engine.report_only(args.run) if hasattr(engine, "report_only") else BacktestEngine(args.base_dir).report_only(args.run)
        print(json.dumps(report, indent=2))
        return 0

    if args.dataset != "v2":
        logger.error("Only dataset v2 is supported")
        return 2

    config = BacktestConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        initial_equity=args.initial_equity,
        seed=args.seed,
        split=args.split,
        strategy=StrategyConfig(
            buy_threshold=args.buy_threshold,
            sell_threshold=args.sell_threshold,
        ),
        risk=RiskConfig(risk_pct=_risk_fraction(args)),
        broker=BrokerConfig(
            spread_points=args.spread,
            slippage_points=args.slippage,
            commission_per_trade=args.commission,
        ),
    )

    if args.phase9_7:
        run_id = args.run or phase9_7_default_run_id()
        result = Phase97BacktestEngine(base_dir=args.base_dir).run(config, run_id=run_id, seed=args.seed)
        print(json.dumps(result.to_dict(), indent=2))
        logger.info(
            "Phase 9.7 backtest complete: %s trades, run_id=%s, recommendation=%s",
            result.num_trades,
            result.run_id,
            result.recommendation,
        )
        if result.leakage_audit != "PASS":
            logger.error("Leakage audit failed")
            return 1
        return 0

    if not args.model:
        logger.error("--model is required unless using --phase9-7 or --report-only")
        return 2

    result = BacktestEngine(base_dir=args.base_dir).run(args.model, config, run_id=args.run)
    print(json.dumps(result.to_dict(), indent=2))
    logger.info("Backtest complete: %s trades, run_id=%s", result.num_trades, result.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
