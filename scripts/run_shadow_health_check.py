#!/usr/bin/env python3
"""Phase 10.5 — shadow health check and error audit CLI."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import (
    ml_live_shadow_context_path,
    ml_live_shadow_metrics_path,
    ml_live_shadow_report_path,
    ml_trade_integrity_invalid_path,
    phase10_5_error_audit_path,
)
from tradingbot.ml.integration.error_audit.error_report import build_error_audit_report, save_error_audit_report
from tradingbot.ml.integration.error_audit.shadow_health_check import ShadowHealthCheck
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shadow health check (Phase 10.5)")
    parser.add_argument("--run", default="stability_run_v1", help="Shadow/monitor run id")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--audit-only", action="store_true", help="Only generate error audit JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    violations = scan_live_shadow_ast()
    if violations:
        logger.error("AST violations: %s", violations)
        return 2

    contexts_path = ml_live_shadow_context_path(args.run, args.base_dir)
    if not contexts_path.is_file():
        logger.error("Run not found: %s", contexts_path)
        return 1

    contexts = json.loads(contexts_path.read_text(encoding="utf-8"))
    metrics = {}
    metrics_path = ml_live_shadow_metrics_path(args.run, args.base_dir)
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    invalid_path = ml_trade_integrity_invalid_path(args.run, args.base_dir)
    invalid_count = 0
    if invalid_path.is_file():
        invalid_count = len(json.loads(invalid_path.read_text(encoding="utf-8")))

    recovery = None
    report_path = ml_live_shadow_report_path(args.run, args.base_dir)
    if report_path.is_file():
        recovery = json.loads(report_path.read_text(encoding="utf-8")).get("recovery")

    health = ShadowHealthCheck().evaluate_artifacts(
        run_id=args.run,
        contexts=contexts,
        metrics=metrics,
        invalid_trades=invalid_count,
        recovery=recovery,
    )

    audit = build_error_audit_report(
        run_id=args.run,
        contexts=contexts,
        health=health.to_dict(),
        source_paths={"kernel_context": str(contexts_path)},
    )
    out = save_error_audit_report(audit, args.base_dir)
    logger.info("Error audit -> %s", out)

    print(json.dumps({"health": health.to_dict(), "audit_path": str(out)}, indent=2))
    return 0 if health.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
