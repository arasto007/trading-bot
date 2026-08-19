"""Phase 3.1 dataset hardening orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.label_quality import LabelQualityValidator
from tradingbot.ml.dataset.leakage_report import save_leakage_audit
from tradingbot.ml.dataset.schema import DatasetBuildConfig
from tradingbot.ml.dataset.statistics import save_dataset_statistics

logger = logging.getLogger(__name__)


def run_dataset_hardening(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    config: DatasetBuildConfig,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Run Phase 3.1 statistics, label quality, fingerprint, and leakage audit.

    Returns summary dict for manifest enrichment.
    """
    summary: dict[str, Any] = {}

    try:
        stats_path = save_dataset_statistics(df, symbol, timeframe, base_dir)
        summary["statistics_report"] = str(stats_path)
    except Exception as exc:
        logger.warning("Dataset statistics failed: %s", exc)

    try:
        lq = LabelQualityValidator().validate(df)
        summary["label_quality"] = lq.to_dict()
    except Exception as exc:
        logger.warning("Label quality validation failed: %s", exc)

    try:
        fp = compute_dataset_fingerprint(df, config)
        summary["fingerprint"] = fp.to_dict()
    except Exception as exc:
        logger.warning("Dataset fingerprint failed: %s", exc)

    try:
        audit_path = save_leakage_audit(df, symbol, timeframe, base_dir)
        summary["leakage_audit_report"] = str(audit_path)
    except Exception as exc:
        logger.warning("Leakage audit failed: %s", exc)

    return summary
