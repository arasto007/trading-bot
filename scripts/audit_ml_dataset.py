#!/usr/bin/env python3
"""Phase 8.2 — ML dataset quality and research audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.dataset.release_manager import DatasetReleaseManager
from tradingbot.ml.dataset.research_audit import DatasetResearchAudit
from tradingbot.ml.dataset.schema import DatasetBuildConfig
from tradingbot.ml.dataset.store import DatasetStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit production ML dataset (Phase 8.2)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--audit", action="store_true", help="Run full research audit")
    parser.add_argument("--features", action="store_true", help="Run feature quality analysis only")
    parser.add_argument("--release", action="store_true", help="Freeze validated dataset release")
    parser.add_argument("--version", default="1", help="Release version (default: 1)")
    args = parser.parse_args()

    if not args.audit and not args.features and not args.release:
        parser.error("Specify one of --audit, --features, or --release")

    cfg = DatasetBuildConfig(symbol=args.symbol.upper(), timeframe=args.timeframe.upper())
    auditor = DatasetResearchAudit(args.symbol, timeframe=args.timeframe, config=cfg)

    if args.features:
        result = auditor.run_features_only()
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.passed else 1

    if args.audit:
        result = auditor.run_full_audit()
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.passed else 1

    store = DatasetStore()
    df = store.load(args.symbol, args.timeframe)
    if df is None or df.empty:
        print(json.dumps({"status": "fail", "error": "no_dataset"}, indent=2))
        return 1

    audit = auditor.run_full_audit()
    if audit.status == "fail":
        print(json.dumps({"status": "fail", "error": "audit_failed", "audit": audit.to_dict()}, indent=2))
        return 1

    manager = DatasetReleaseManager(args.symbol, timeframe=args.timeframe, config=cfg)
    release = manager.create_release(df, version=args.version, research_report=audit.to_dict())
    print(json.dumps(release.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
