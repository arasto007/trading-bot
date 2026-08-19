"""Phase 24C — latency profiling deliverable tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24c"

VERDICT_OPTIONS = {"ONE_BOTTLENECK", "MULTIPLE_BOTTLENECKS", "NO_BOTTLENECK_FOUND"}

REQUIRED_STAGES = (
    "feature_builder_compute_at",
    "pipeline_cache_unified_frame",
    "produce_unified_signal_total",
    "predict_proba_only",
)


class TestPhase24CProfiler(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.ml.research.phase24c.run_profiling import write_deliverables

        cls.result = write_deliverables(out_dir=PHASE_DIR, quick=True)

    def test_deliverables_written(self) -> None:
        self.assertEqual(self.result["count"], 7)
        self.assertIn(self.result["verdict"], VERDICT_OPTIONS)

    def test_stage_timings_have_percentiles(self) -> None:
        payload = json.loads((PHASE_DIR / "stage_timings.json").read_text(encoding="utf-8"))
        total = payload["stages"].get("produce_unified_signal_total", {})
        self.assertGreater(total.get("count", 0), 0)
        for key in ("mean_ms", "median_ms", "p95_ms", "p99_ms", "max_ms"):
            self.assertIn(key, total)

    def test_required_stages_measured(self) -> None:
        payload = json.loads((PHASE_DIR / "stage_timings.json").read_text(encoding="utf-8"))
        for stage in REQUIRED_STAGES:
            self.assertIn(stage, payload["stages"], f"missing stage {stage}")
            self.assertGreater(payload["stages"][stage]["count"], 0)

    def test_cache_statistics(self) -> None:
        payload = json.loads((PHASE_DIR / "cache_statistics.json").read_text(encoding="utf-8"))
        self.assertIn("pipeline_cache_feature", payload)
        self.assertFalse(payload["feature_builder"]["internal_cache"])

    def test_flamegraph_structure(self) -> None:
        payload = json.loads((PHASE_DIR / "pipeline_flamegraph.json").read_text(encoding="utf-8"))
        self.assertIn("root", payload)
        self.assertEqual(payload["root"]["name"], "kernel_adapter_total")

    def test_bottleneck_report_verdict(self) -> None:
        payload = json.loads((PHASE_DIR / "bottleneck_report.json").read_text(encoding="utf-8"))
        self.assertIn(payload["verdict"], VERDICT_OPTIONS)
        self.assertIn("primary_bottleneck", payload)
        self.assertEqual(payload["evidence"], "All timings from perf_counter — no estimates")

    def test_final_report_not_modified(self) -> None:
        payload = json.loads((PHASE_DIR / "phase24c_final_report.json").read_text(encoding="utf-8"))
        self.assertFalse(payload["production_modified"])


if __name__ == "__main__":
    unittest.main()
