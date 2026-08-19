"""Phase 27K — losing trade root cause deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27k"

DELIVERABLES = [
    "losing_trade_log.json",
    "entry_conditions.json",
    "first_bar_analysis.json",
    "mae_mfe_analysis.json",
    "stoploss_quality.json",
    "false_signal_classification.json",
    "regime_loss_analysis.json",
    "engine_loss_analysis.json",
    "confidence_loss_analysis.json",
    "root_cause_rank.json",
    "final_report.json",
]

VERDICTS = {"LOSING_TRADES_ROOT_CAUSE_IDENTIFIED", "LOSING_TRADES_ROOT_CAUSE_NOT_IDENTIFIED"}
EXPECTED_LOSERS = 353
EXPECTED_TRADES = 575


class TestPhase27KDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "final_report.json").is_file():
            raise unittest.SkipTest("Phase 27K deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_loser_count(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("losing_trades"), EXPECTED_LOSERS)
        self.assertEqual(report.get("total_trades"), EXPECTED_TRADES)

    def test_losing_trade_log_fields(self) -> None:
        log = json.loads((PHASE_DIR / "losing_trade_log.json").read_text(encoding="utf-8"))
        self.assertEqual(log.get("count"), EXPECTED_LOSERS)
        sample = (log.get("trades") or [None])[0]
        self.assertIsNotNone(sample)
        for key in ("direction", "rsi", "adx", "mae_r", "mfe_r", "false_signal_class", "first_bars"):
            self.assertIn(key, sample)

    def test_false_signal_classification(self) -> None:
        fs = json.loads((PHASE_DIR / "false_signal_classification.json").read_text(encoding="utf-8"))
        self.assertEqual(fs.get("loser_count"), EXPECTED_LOSERS)
        self.assertTrue(fs.get("dominant_class"))

    def test_mae_mfe_analysis(self) -> None:
        mm = json.loads((PHASE_DIR / "mae_mfe_analysis.json").read_text(encoding="utf-8"))
        self.assertIn("ever_profitable_before_sl_pct", mm)
        self.assertGreater(mm.get("average_mae_r", 0), 0.5)

    def test_root_cause_ranked(self) -> None:
        rc = json.loads((PHASE_DIR / "root_cause_rank.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(rc.get("ranked_causes") or []), 5)
        self.assertTrue(rc.get("primary_root_cause"))

    def test_confidence_buckets(self) -> None:
        conf = json.loads((PHASE_DIR / "confidence_loss_analysis.json").read_text(encoding="utf-8"))
        buckets = conf.get("buckets") or {}
        self.assertIn("0.90-1.00", buckets)


if __name__ == "__main__":
    unittest.main()
