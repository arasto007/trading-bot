#!/usr/bin/env python3
"""Phase 20A — controlled live capital deployment."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase20a.config import (
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    MAX_RISK_PCT,
    MIN_RISK_PCT,
    DeploymentConfig,
    ENV_APPROVAL,
    ENV_ENABLE_LIVE,
)
from tradingbot.ml.phase20a.orchestrator import start_live_deployment


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 20A live capital deployment")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--risk", type=float, default=2.0, help="Risk %% of account (1-5)")
    p.add_argument("--base-dir", default=None)
    p.add_argument("--skip-certification", action="store_true")
    p.add_argument("--skip-preflight", action="store_true")
    p.add_argument("--init-only", action="store_true", help="Validate and init reports without live loop")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    risk = max(MIN_RISK_PCT, min(MAX_RISK_PCT, args.risk / 100.0))
    config = DeploymentConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        risk_pct=risk,
        skip_certification_check=args.skip_certification,
        skip_preflight=args.skip_preflight,
        base_dir=args.base_dir,
    )

    if args.init_only:
        from tradingbot.ml.phase20a.certification_gate import verify_certification
        from tradingbot.ml.phase20a.config import VERDICT_STARTED, apply_certified_env
        from tradingbot.ml.phase20a.reporter import Phase20aReporter

        apply_certified_env(config)
        cert = verify_certification(base_dir=config.base_dir)
        if not cert.get("passed") and not args.skip_certification:
            print(f"CERTIFICATION_FAILED: {cert.get('verdict')}", file=sys.stderr)
            return 1
        reporter = Phase20aReporter(base_dir=config.base_dir)
        reporter.write_final_report({
            "verdict": VERDICT_STARTED,
            "mode": "init_only",
            "certification": cert,
        })
        print(VERDICT_STARTED)
        return 0

    start_live_deployment(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
