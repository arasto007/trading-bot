"""Phase 24B — architecture audit deliverable tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24b"

REQUIRED_FILES = (
    "architecture_overview.json",
    "module_inventory.json",
    "call_graph.json",
    "execution_graph.json",
    "feature_graph.json",
    "probability_graph.json",
    "confidence_graph.json",
    "decision_graph.json",
    "hold_graph.json",
    "filter_graph.json",
    "risk_graph.json",
    "runtime_vs_research.json",
    "ownership_matrix.json",
    "dependency_matrix.json",
    "configuration_inventory.json",
    "threshold_inventory.json",
    "live_pipeline_trace.json",
    "research_pipeline_trace.json",
    "architecture_findings.json",
    "phase24b_final_report.json",
)


class TestPhase24BArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.ml.research.phase24b.run_audit import write_artifacts

        write_artifacts(out_dir=PHASE_DIR)

    def test_all_required_json_files_exist(self) -> None:
        for name in REQUIRED_FILES:
            path = PHASE_DIR / name
            self.assertTrue(path.is_file(), f"missing {name}")

    def test_final_report_has_eight_answers(self) -> None:
        payload = json.loads((PHASE_DIR / "phase24b_final_report.json").read_text(encoding="utf-8"))
        answers = payload["answers"]
        for key in (
            "1_how_system_works",
            "2_major_module_responsibilities",
            "3_independent_modules",
            "4_tightly_coupled_modules",
            "5_architecture_assumptions",
            "6_safe_future_modifications",
            "7_dangerous_future_modifications",
            "8_investigate_before_changes",
        ):
            self.assertIn(key, answers)

    def test_live_pipeline_reaches_order_send(self) -> None:
        payload = json.loads((PHASE_DIR / "live_pipeline_trace.json").read_text(encoding="utf-8"))
        terminal = payload["terminal_live_order"]
        self.assertEqual(terminal["function"], "mt5.order_send")

    def test_verdict_documented(self) -> None:
        payload = json.loads((PHASE_DIR / "phase24b_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["verdict"], "ARCHITECTURE_FULLY_TRACED")
        self.assertFalse(payload["production_modified"])

    def test_hold_graph_covers_ml_stages(self) -> None:
        payload = json.loads((PHASE_DIR / "hold_graph.json").read_text(encoding="utf-8"))
        ids = {h["id"] for h in payload["holds"]}
        for expected in ("decision_hold", "rsi_filter_hold", "health_gate_fallback"):
            self.assertIn(expected, ids)

    def test_runtime_vs_research_divergence_documented(self) -> None:
        payload = json.loads((PHASE_DIR / "runtime_vs_research.json").read_text(encoding="utf-8"))
        areas = {d["area"] for d in payload["divergences"]}
        self.assertIn("market_data_source", areas)


if __name__ == "__main__":
    unittest.main()
