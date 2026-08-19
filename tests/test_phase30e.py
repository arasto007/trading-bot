"""Phase 30E — MT5 capability forensic audit tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase30e"

DELIVERABLES = [
    "mt5_capability_matrix.json",
    "broker_capability_matrix.json",
    "api_function_mapping.json",
    "terminal_limitations.json",
    "broker_limitations.json",
    "collectable_metrics.json",
    "uncollectable_metrics.json",
    "replacement_metrics.json",
    "collector_architecture.json",
    "implementation_risk_matrix.json",
    "phase30e_final_report.json",
]

VERDICTS = {"MT5_READY_FOR_COLLECTION", "MT5_LIMITATIONS_REQUIRE_REDESIGN"}


class TestPhase30E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase30e_final_report.json").is_file():
            from tradingbot.ml.research.phase30e.run_investigation import run_phase30e

            run_phase30e()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "phase30e_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report["verdict"], VERDICTS)
        self.assertFalse(report.get("production_modified", True))

    def test_capability_matrix_coverage(self) -> None:
        matrix = json.loads((PHASE_DIR / "mt5_capability_matrix.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(matrix["summary"]["total_metrics"], 40)
        for row in matrix["rows"]:
            self.assertIn("metric", row)
            self.assertIn("implementation_risk", row)
            self.assertIn(row["implementation_risk"], {"Low", "Medium", "High", "Impossible"})

    def test_no_required_impossible_blockers(self) -> None:
        risk = json.loads(
            (PHASE_DIR / "implementation_risk_matrix.json").read_text(encoding="utf-8")
        )
        self.assertEqual(risk["summary"]["required_blockers"], 0)

    def test_uncollectable_have_replacements(self) -> None:
        uncol = json.loads((PHASE_DIR / "uncollectable_metrics.json").read_text(encoding="utf-8"))
        repl = json.loads((PHASE_DIR / "replacement_metrics.json").read_text(encoding="utf-8"))
        self.assertGreater(uncol["count"], 0)
        self.assertGreaterEqual(len(repl["replacements"]), uncol["count"])

    def test_api_mapping_covers_phase30d_datasets(self) -> None:
        mapping = json.loads((PHASE_DIR / "api_function_mapping.json").read_text(encoding="utf-8"))
        datasets = {m["dataset"] for m in mapping["mappings"]}
        for expected in ("TickStream", "ExecutionFills", "OrderAttempts", "SymbolInfoDaily", "AccountSnapshots"):
            self.assertIn(expected, datasets)

    def test_collector_architecture_read_only_tick_path(self) -> None:
        arch = json.loads((PHASE_DIR / "collector_architecture.json").read_text(encoding="utf-8"))
        tick = next(p for p in arch["processes"] if p["name"] == "TickPoller")
        self.assertTrue(tick["read_only"])
        self.assertIn("symbol_info_tick", tick["api"])

    def test_collectable_includes_critical_spread_slippage(self) -> None:
        col = json.loads((PHASE_DIR / "collectable_metrics.json").read_text(encoding="utf-8"))
        for metric in ("Bid", "Ask", "Spread", "Entry slippage", "Exit slippage", "Retcodes"):
            self.assertIn(metric, col["metrics"])


if __name__ == "__main__":
    unittest.main()
