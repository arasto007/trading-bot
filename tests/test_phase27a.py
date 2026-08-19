"""Phase 27A deliverable presence and verdict checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27a"

DELIVERABLES = [
    "backtest_summary.json",
    "profitability_metrics.json",
    "trade_statistics.json",
    "buy_sell_analysis.json",
    "regime_analysis.json",
    "engine_analysis.json",
    "risk_analysis.json",
    "decision_analysis.json",
    "hold_analysis.json",
    "latency_analysis.json",
    "cache_analysis.json",
    "system_health.json",
    "journal_integrity.json",
    "equity_curve.json",
    "drawdown_curve.json",
    "trade_log.json",
    "paper_readiness.json",
    "integrity_score.json",
    "critical_findings.json",
    "phase27a_final_report.json",
]

VERDICTS = {"READY_FOR_PAPER_TRADING", "NOT_READY_FOR_PAPER_TRADING"}


class TestPhase27ADeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase27a_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_replay_metadata(self) -> None:
        summary = json.loads((PHASE_DIR / "backtest_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary.get("replay_days"), 30)
        self.assertEqual(summary.get("pipeline"), "phase25b.run_unified_pipeline_replay")


if __name__ == "__main__":
    unittest.main()
