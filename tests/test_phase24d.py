"""Phase 24D — optimization design deliverable tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24d"

VERDICTS = {
    "SAFE_INCREMENTAL_OPTIMIZATION",
    "SAFE_IN_MEMORY_CACHE",
    "SAFE_FEATURE_CACHE",
    "NO_SAFE_OPTIMIZATION",
}


class TestPhase24DDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.ml.research.phase24d.run_investigation import write_deliverables

        cls.result = write_deliverables(out_dir=PHASE_DIR, quick=True)

    def test_all_files_exist(self) -> None:
        expected = (
            "unified_frame_trace.json",
            "merge_breakdown.json",
            "duplicate_work_report.json",
            "featurebuilder_analysis.json",
            "cache_key_analysis.json",
            "dataset_usage.json",
            "optimization_simulation.json",
            "risk_analysis.json",
            "recommended_strategy.json",
            "phase24d_final_report.json",
        )
        for name in expected:
            self.assertTrue((PHASE_DIR / name).is_file(), name)

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result["verdict"], VERDICTS)

    def test_unified_frame_trace_has_why_bottleneck(self) -> None:
        payload = json.loads((PHASE_DIR / "unified_frame_trace.json").read_text(encoding="utf-8"))
        self.assertIn("why_bottleneck", payload)
        self.assertGreater(len(payload["operation_timings"]), 5)

    def test_cache_key_invalidates_on_timestamp(self) -> None:
        payload = json.loads((PHASE_DIR / "cache_key_analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["invalidating_field"], "tail.index[-1] (last closed bar timestamp)")

    def test_three_strategies_simulated(self) -> None:
        payload = json.loads((PHASE_DIR / "optimization_simulation.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["strategies"]), 3)

    def test_no_production_modified(self) -> None:
        payload = json.loads((PHASE_DIR / "phase24d_final_report.json").read_text(encoding="utf-8"))
        self.assertFalse(payload["production_modified"])


if __name__ == "__main__":
    unittest.main()
