#!/usr/bin/env python3
"""Run ML stress tests — Phase 7.1 simulation only."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.stress.chaos_tests import StressSandbox
from tradingbot.ml.stress.resilience import ResilienceEvaluator
from tradingbot.ml.stress.simulator import StressScenarioRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="ML shadow stress testing — simulation only")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--output-dir", default=None, help="Optional report output base dir")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="ml_stress_") as tmp:
        sandbox = StressSandbox.create(Path(tmp), args.symbol, args.timeframe)
        runner = StressScenarioRunner(symbol=args.symbol, timeframe=args.timeframe, stale_hours=1.0)
        results = runner.run_all(sandbox)

    evaluator = ResilienceEvaluator(base_dir=args.output_dir)
    metrics = evaluator.evaluate(results)
    if args.output_dir:
        evaluator.write_report(results, metrics)

    summary = {
        "system_resilience": metrics.system_resilience,
        "scenarios_tested": metrics.scenarios_tested,
        "detected": metrics.detected,
        "recovery_success": metrics.recovery_success,
        "safe_mode_triggered": metrics.safe_mode_triggered,
    }
    print(json.dumps(summary, indent=2))
    print()
    print("Execution:\nDISABLED")
    print("Live Trading:\nUNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
