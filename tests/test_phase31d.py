"""Phase 31D — simulator parity audit tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase31d"

DELIVERABLES = [
    "trade_diff_report.json",
    "exit_diff_report.json",
    "accounting_diff.json",
    "journal_diff.json",
    "execution_diff.json",
    "candle_alignment.json",
    "root_cause_analysis.json",
    "simulator_parity_report.json",
    "phase31d_final_report.json",
]

VERDICTS = {"SIMULATOR_PARITY_CONFIRMED", "SIMULATOR_PARITY_FAILED"}


class TestPhase31D(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase31d_final_report.json").is_file():
            from tradingbot.ml.research.phase31d.run_investigation import run_phase31d

            run_phase31d()

    def _final(self) -> dict:
        return json.loads((PHASE_DIR / "phase31d_final_report.json").read_text(encoding="utf-8"))

    def _repaired(self) -> bool:
        return bool(self._final().get("repaired_mode"))

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        doc = self._final()
        self.assertIn(doc["verdict"], VERDICTS)
        self.assertFalse(doc.get("production_modified", True))

    def test_trade_count_489(self) -> None:
        doc = json.loads((PHASE_DIR / "trade_diff_report.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["trade_count"], 489)
        self.assertEqual(len(doc["trades"]), 489)

    def test_production_pf(self) -> None:
        doc = self._final()
        if self._repaired():
            self.assertGreater(doc["production_pf"], 1.2)
        else:
            self.assertAlmostEqual(doc["production_pf"], 1.211, delta=0.05)

    def test_simulator_pf(self) -> None:
        doc = self._final()
        if self._repaired():
            self.assertAlmostEqual(doc["simulator_pf"], doc["production_pf"], delta=0.01)
        else:
            self.assertAlmostEqual(doc["simulator_pf"], 2.0626, delta=0.1)

    def test_parity_verdict(self) -> None:
        doc = self._final()
        if self._repaired():
            self.assertEqual(doc["verdict"], "SIMULATOR_PARITY_CONFIRMED")
            self.assertLess(doc["pf_gap_pct"], 0.5)
        else:
            self.assertEqual(doc["verdict"], "SIMULATOR_PARITY_FAILED")
            self.assertGreater(doc["pf_gap_pct"], 0.5)

    def test_root_cause_truncation(self) -> None:
        doc = json.loads((PHASE_DIR / "root_cause_analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["dominant_root_cause"], "RC01")

    def test_execution_diff(self) -> None:
        doc = json.loads((PHASE_DIR / "execution_diff.json").read_text(encoding="utf-8"))
        if self._repaired():
            self.assertGreater(doc.get("repaired_oracle_match_pct", 0), 99.0)
        else:
            self.assertGreater(doc.get("truncated_replay_match_pct", 0), 90.0)

    def test_exit_diff_field_mismatches(self) -> None:
        doc = json.loads((PHASE_DIR / "exit_diff_report.json").read_text(encoding="utf-8"))
        if not self._repaired():
            self.assertIn("duration_bars", doc["field_mismatch_counts"])

    def test_accounting_diff_quantified(self) -> None:
        doc = json.loads((PHASE_DIR / "accounting_diff.json").read_text(encoding="utf-8"))
        if self._repaired():
            self.assertLess(doc["pf_gap_pct"], 0.5)
        else:
            self.assertGreater(doc["pf_gap_pct"], 50.0)

    def test_journal_integrity(self) -> None:
        doc = json.loads((PHASE_DIR / "journal_diff.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["entry_timestamp_consistency"])

    def test_candle_alignment_majority(self) -> None:
        doc = json.loads((PHASE_DIR / "candle_alignment.json").read_text(encoding="utf-8"))
        self.assertGreater(doc["aligned_trades"], 400)

    def test_simulator_parity_report_criteria(self) -> None:
        doc = json.loads((PHASE_DIR / "simulator_parity_report.json").read_text(encoding="utf-8"))
        if self._repaired():
            self.assertEqual(doc["verdict"], "SIMULATOR_PARITY_CONFIRMED")
        else:
            self.assertEqual(doc["verdict"], "SIMULATOR_PARITY_FAILED")

    def test_per_trade_diff_has_primary_cause(self) -> None:
        doc = json.loads((PHASE_DIR / "trade_diff_report.json").read_text(encoding="utf-8"))
        causes = {t["primary_cause"] for t in doc["trades"]}
        self.assertTrue(len(causes) >= 1)

    def test_root_cause_has_file_and_function(self) -> None:
        doc = json.loads((PHASE_DIR / "root_cause_analysis.json").read_text(encoding="utf-8"))
        top = doc["ranked_causes"][0]
        self.assertIn("file", top)
        self.assertIn("function", top)
        self.assertGreaterEqual(top["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()
