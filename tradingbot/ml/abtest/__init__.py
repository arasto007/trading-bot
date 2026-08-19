"""A/B shadow integration layer — Phase 6.0."""

from __future__ import annotations

from tradingbot.ml.abtest.comparator import ABComparator
from tradingbot.ml.abtest.logger import ABTestLogger, ab_records_path
from tradingbot.ml.abtest.metrics import ArmMetrics, compute_arm_metrics
from tradingbot.ml.abtest.report import ABReportGenerator, ab_test_report_path, winner_display, write_ab_test_report
from tradingbot.ml.abtest.schema import (
    ABDecisionRecord,
    ABTestReport,
    STATUS_INSUFFICIENT,
    WINNER_HYBRID,
    WINNER_RULE,
    WINNER_TIE,
)

__all__ = [
    "ABComparator",
    "ABDecisionRecord",
    "ABReportGenerator",
    "ABTestLogger",
    "ABTestReport",
    "ArmMetrics",
    "STATUS_INSUFFICIENT",
    "WINNER_HYBRID",
    "WINNER_RULE",
    "WINNER_TIE",
    "ab_records_path",
    "ab_test_report_path",
    "compute_arm_metrics",
    "winner_display",
    "write_ab_test_report",
]
