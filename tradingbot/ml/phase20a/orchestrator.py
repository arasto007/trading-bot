"""Phase 20A — live capital deployment orchestrator."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.phase20a.certification_gate import verify_certification
from tradingbot.ml.phase20a.config import VERDICT_STARTED, DeploymentConfig, is_live_execution_enabled
from tradingbot.ml.phase20a.deployment_runner import Phase20aDeploymentRunner

logger = logging.getLogger(__name__)


def start_live_deployment(config: DeploymentConfig | None = None) -> dict[str, Any]:
    """
    Start Phase 20A controlled live deployment.

    Returns verdict LIVE_DEPLOYMENT_STARTED after validation and initialization.
    Blocks in run_forever() until stopped.
    """
    cfg = config or DeploymentConfig()

    if not cfg.skip_certification_check:
        cert = verify_certification(base_dir=cfg.base_dir)
        if not cert.get("passed"):
            raise RuntimeError(f"Phase19D certification failed: {cert.get('verdict')}")

    runner = Phase20aDeploymentRunner(cfg)
    preflight = runner.preflight()
    if not preflight.get("preflight_pass"):
        raise RuntimeError(f"Live preflight failed: {preflight}")

    started_at = datetime.now(timezone.utc).isoformat()

    session = {
        "phase": "20A",
        "verdict": VERDICT_STARTED,
        "started_at": started_at,
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe,
        "risk_pct": cfg.risk_pct,
        "max_open_positions": cfg.max_open_positions,
        "trend_model": "trend_rf_v41",
        "range_model": "phase9_9",
        "filters": ["rsi_mid", "adx_15_50"],
        "live_orders_enabled": is_live_execution_enabled(),
        "certification": "APPROVED_FOR_FULL_PRODUCTION",
        "preflight": preflight,
    }
    runner.reporter.write_session_summary(session)
    runner.reporter.write_final_report({
        **session,
        "status": VERDICT_STARTED,
        "reports_dir": str(runner.reporter.output_dir),
        "rollback": {
            "trend": "TREND_MODEL_VERSION=v40",
            "filters": "ENABLE_RSI_FILTER=false ENABLE_ADX_FILTER=false",
        },
    })

    logger.info("Phase20A: %s", VERDICT_STARTED)
    print(VERDICT_STARTED)

    runner.run()

    return {
        "verdict": VERDICT_STARTED,
        "session": session,
        "reports_dir": str(runner.reporter.output_dir),
    }
