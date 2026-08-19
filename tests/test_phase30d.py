"""Phase 30D — broker fingerprint collection design tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase30d"

DELIVERABLES = [
    "broker_fingerprint_schema.json",
    "required_datasets.json",
    "tick_collection_plan.json",
    "execution_collection_plan.json",
    "latency_collection_plan.json",
    "spread_collection_plan.json",
    "slippage_collection_plan.json",
    "broker_statistics_requirements.json",
    "minimum_sample_requirements.json",
    "calibration_readiness.json",
    "collection_priority_matrix.json",
    "phase30d_final_report.json",
]

VERDICTS = {"READY_FOR_DATA_COLLECTION", "MORE_DATA_REQUIREMENTS_NEEDED"}

METRIC_FIELDS = {
    "metric",
    "definition",
    "sampling_frequency",
    "collection_method",
    "storage_format",
    "required_sample_size",
    "expected_collection_duration",
    "calibration_importance",
    "confidence",
}


class TestPhase30D(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase30d_final_report.json").is_file():
            from tradingbot.ml.research.phase30d.run_investigation import run_phase30d

            run_phase30d()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_final_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "phase30d_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report["verdict"], VERDICTS)
        self.assertFalse(report.get("production_modified", True))

    def test_all_metrics_have_required_fields(self) -> None:
        doc = json.loads(
            (PHASE_DIR / "broker_statistics_requirements.json").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(doc["metric_count"], 30)
        for entry in doc["metrics"]:
            missing = METRIC_FIELDS - set(entry.keys())
            self.assertFalse(missing, msg=f"{entry.get('metric')}: {missing}")
            self.assertGreaterEqual(entry["confidence"], 0)
            self.assertLessEqual(entry["confidence"], 100)

    def test_schema_tables_and_integrity(self) -> None:
        schema = json.loads((PHASE_DIR / "broker_fingerprint_schema.json").read_text(encoding="utf-8"))
        tables = schema["tables"]
        for key in ("ticks", "executions", "orders", "metadata"):
            self.assertIn(key, tables)
        self.assertEqual(schema["timezone"], "UTC only — all timestamps stored as UTC microseconds")
        self.assertIn("integrity", schema)
        self.assertIn("tick_store_path", schema)

    def test_minimum_samples(self) -> None:
        mins = json.loads((PHASE_DIR / "minimum_sample_requirements.json").read_text(encoding="utf-8"))
        m = mins["minimums"]
        self.assertGreaterEqual(m["ticks_total"], 500_000)
        self.assertGreaterEqual(m["executions_total"], 200)
        self.assertGreaterEqual(m["trading_days"], 30)
        self.assertGreaterEqual(m["weekend_transitions"], 4)

    def test_calibration_checklist(self) -> None:
        doc = json.loads((PHASE_DIR / "calibration_readiness.json").read_text(encoding="utf-8"))
        required = [c for c in doc["checklist"] if c["required"]]
        self.assertGreaterEqual(len(required), 10)
        self.assertIn("statistically_reliable_when", doc)

    def test_execution_plan_requires_demo_fills(self) -> None:
        plan = json.loads(
            (PHASE_DIR / "execution_collection_plan.json").read_text(encoding="utf-8")
        )
        paper = next(m for m in plan["modes"] if m["mode"] == "paper_export")
        self.assertEqual(paper["adequacy"], "INSUFFICIENT for slippage calibration")
        self.assertEqual(plan["recommended"], "demo_live 0.01 lot XAUUSD M5 aligned with bot signals")

    def test_collection_priority_order(self) -> None:
        matrix = json.loads(
            (PHASE_DIR / "collection_priority_matrix.json").read_text(encoding="utf-8")
        )
        ranks = [p["rank"] for p in matrix["priority"]]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(matrix["priority"][0]["dataset"], "TickStream")


if __name__ == "__main__":
    unittest.main()
