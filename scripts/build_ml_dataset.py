#!/usr/bin/env python3
"""Phase 8.1 / 8.5 — production ML dataset build and training-readiness validation."""

from __future__ import annotations

import logging
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.dataset.deep_audit import DatasetDeepAuditor
from tradingbot.ml.dataset.phase9_production_build import Phase91ProductionBuilder
from tradingbot.ml.dataset.production_builder import ProductionDatasetBuilder
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DatasetBuildConfig
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.train_readiness_report import TrainReadinessAnalyzer


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Build production ML dataset (Phase 8.1 / 8.5)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run raw data preflight checks only",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run full production dataset build (Phase 8.1)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing labeled dataset on disk",
    )
    parser.add_argument(
        "--sanity",
        action="store_true",
        help="Run Phase 8.5 sanity gate on existing dataset",
    )
    parser.add_argument(
        "--build-v2",
        action="store_true",
        help="Build training-ready dataset V2 with sanity gate",
    )
    parser.add_argument(
        "--train-ready-report",
        action="store_true",
        help="Generate training readiness report for existing dataset",
    )
    parser.add_argument(
        "--rebuild-source",
        action="store_true",
        help="Rebuild Phase 8.1 source dataset before V2 (requires raw data)",
    )
    parser.add_argument(
        "--phase9-1",
        action="store_true",
        help="Phase 9.1 — full production build from verified 5Y data + validation reports",
    )
    parser.add_argument(
        "--phase9-preflight",
        action="store_true",
        help="Phase 9.1 preflight only (bar counts, OHLC, alignment)",
    )
    parser.add_argument(
        "--phase9-finalize",
        action="store_true",
        help="Phase 9.1 finalize — validate existing v2, patch spread, reports, archive v1",
    )
    parser.add_argument(
        "--deep-audit",
        action="store_true",
        help="Phase 9.1.5 — read-only deep forensic audit of dataset_v2",
    )
    args = parser.parse_args()

    actions = (
        args.preflight_only,
        args.build,
        args.validate_only,
        args.sanity,
        args.build_v2,
        args.train_ready_report,
        args.phase9_1,
        args.phase9_preflight,
        args.phase9_finalize,
        args.deep_audit,
    )
    if not any(actions):
        parser.error(
            "Specify one of --preflight-only, --build, --validate-only, "
            "--sanity, --build-v2, --train-ready-report, --phase9-1, "
            "--phase9-preflight, --phase9-finalize, or --deep-audit"
        )

    cfg = DatasetBuildConfig(symbol=args.symbol.upper(), timeframe=args.timeframe.upper())
    builder = ProductionDatasetBuilder(args.symbol, timeframe=args.timeframe, config=cfg)
    v2 = ProductionDatasetV2Builder(
        args.symbol,
        timeframe=args.timeframe,
        config=cfg,
        rebuild_source=args.rebuild_source,
    )

    if args.deep_audit:
        auditor = DatasetDeepAuditor()
        report, path = auditor.run_and_save(args.symbol, args.timeframe)
        DatasetDeepAuditor.print_summary(report)
        print(json.dumps(report.to_dict(), indent=2))
        print(f"\nReport saved: {path}")
        return 0 if report.status == "PASS" else 1

    if args.phase9_preflight:
        phase9 = Phase91ProductionBuilder(args.symbol, timeframe=args.timeframe)
        preflight, hq, ok = phase9.run_preflight_checks()
        print(json.dumps({"preflight": preflight, "historical_quality": hq, "passed": ok}, indent=2))
        return 0 if ok else 1

    if args.phase9_1:
        result = Phase91ProductionBuilder(args.symbol, timeframe=args.timeframe).build()
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.passed else 1

    if args.phase9_finalize:
        result = Phase91ProductionBuilder(args.symbol, timeframe=args.timeframe).finalize()
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.passed else 1

    if args.preflight_only:
        report = builder.run_preflight()
        print(json.dumps(report, indent=2))
        return 0 if report.get("passed") else 1

    if args.sanity:
        report = v2.run_sanity().to_dict()
        print(json.dumps(report, indent=2))
        return 0 if report.get("passed") and not report.get("blocked") else 1

    if args.train_ready_report:
        store = DatasetStore()
        df = store.load_v2(args.symbol, args.timeframe) or store.load(args.symbol, args.timeframe)
        if df is None or df.empty:
            print(json.dumps({"status": "fail", "error": "no_dataset"}, indent=2))
            return 1
        report, path = TrainReadinessAnalyzer().analyze_and_save(df, args.symbol, args.timeframe)
        payload = report.to_dict()
        payload["report_path"] = str(path)
        print(json.dumps(payload, indent=2))
        return 0 if report.recommended_for_training else 1

    if args.build_v2:
        result = v2.build_v2()
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.passed else 1

    if args.validate_only:
        report = builder.validate_existing()
        print(json.dumps(report, indent=2))
        return 0 if report.get("status") != "fail" else 1

    result = builder.build()
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
