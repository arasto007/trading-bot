"""A/B shadow test report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.abtest.comparator import ABComparator
from tradingbot.ml.abtest.logger import ABTestLogger
from tradingbot.ml.abtest.schema import ABTestReport, STATUS_INSUFFICIENT, WINNER_HYBRID
from tradingbot.ml.memory.store import DecisionMemoryStore


def ab_test_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "ab_test_report.json"


def write_ab_test_report(report: ABTestReport | dict[str, Any], base_dir: str | Path | None = None) -> Path:
    payload = report.to_dict() if isinstance(report, ABTestReport) else dict(report)
    path = ab_test_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


class ABReportGenerator:
    """Run A/B comparison and write report + optional record log."""

    def __init__(
        self,
        *,
        min_samples: int = 100,
        winner_margin: float = 0.05,
        base_dir: str | Path | None = None,
        log_records: bool = True,
    ) -> None:
        self.comparator = ABComparator(min_samples=min_samples, winner_margin=winner_margin)
        self.base_dir = base_dir
        self.log_records = log_records

    def run_from_store(
        self,
        store: DecisionMemoryStore,
        *,
        timeframe: str = "M5",
    ) -> dict[str, Any]:
        decisions = store.load_decisions()
        outcomes = store.load_outcomes_by_id()
        records = self.comparator.build_records(decisions, outcomes)

        if records:
            records[0].symbol = store.symbol
            records[0].timeframe = timeframe.upper()

        if self.log_records and records:
            ABTestLogger(store.symbol, self.base_dir).log_many(records)

        report = self.comparator.compare(records)
        if report.symbol == "" and store.symbol:
            report = ABTestReport(
                **{
                    **report.to_dict(),
                    "symbol": store.symbol,
                    "timeframe": timeframe.upper(),
                }
            )

        write_ab_test_report(report, self.base_dir)
        return report.to_dict()


def winner_display(winner: str) -> str:
    if winner == WINNER_HYBRID:
        return "HYBRID"
    if winner == "RULE_BETTER":
        return "RULE"
    if winner == STATUS_INSUFFICIENT:
        return "INSUFFICIENT_DATA"
    return winner
