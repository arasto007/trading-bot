"""Phase 34B tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERDICTS = {"LABELS_VALID", "LABELS_INVALID", "LABELS_NEEDS_REVIEW", "INSUFFICIENT_DATA"}


class TestPhase34B(unittest.TestCase):
    def test_label_quality_validator_empty(self) -> None:
        import pandas as pd
        from tradingbot.ml.dataset.label_quality import LabelQualityValidator

        v = LabelQualityValidator()
        r = v.validate(pd.DataFrame())
        self.assertEqual(r.status, "fail")

    def test_deliverables_after_run(self) -> None:
        report = PROJECT_ROOT / "phase34b_final_report.json"
        if not report.exists():
            self.skipTest("phase34b not yet run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "34B")
        self.assertIn(data["verdict"], VERDICTS)


if __name__ == "__main__":
    unittest.main()
