"""Phase 1.5.41–1.5.45 — v41 cost sensitivity stays offline and uncalibrated."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "tradingbot" / "ml" / "research" / "v41_isolated"


class TestCostFormulas(unittest.TestCase):
    def test_flat_cost_shifts_every_trade(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import apply_flat_cost_r, book_metrics

        net = apply_flat_cost_r([2.0, -1.0, 2.0], 0.1)
        self.assertEqual(net, [1.9, -1.1, 1.9])
        zero = book_metrics([2.0, -1.0, 2.0], cost_r=0.0)
        taxed = book_metrics([2.0, -1.0, 2.0], cost_r=0.1)
        self.assertGreater(zero["expectancy"], taxed["expectancy"])
        self.assertAlmostEqual(zero["expectancy"] - 0.1, taxed["expectancy"], places=5)

    def test_break_even_expectancy_equals_mean_r(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import break_even_cost_r, book_metrics

        rs = [2.0, 2.0, -1.0, -1.0, 0.5]
        be = break_even_cost_r(rs)
        self.assertAlmostEqual(be["expectancy_zero_cost_r"], sum(rs) / len(rs), places=5)
        at = book_metrics(rs, cost_r=be["expectancy_zero_cost_r"])
        self.assertAlmostEqual(at["expectancy"] or 0.0, 0.0, places=5)
        self.assertTrue(be["not_evidence_of_actual_costs"])

    def test_point_to_r_conversion(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import assumption_cost_from_points

        costs = assumption_cost_from_points([2.0, 1.0, 0.5], 0.50)
        self.assertEqual(costs, [0.25, 0.5, 1.0])

    def test_insufficient_slice_flag(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import _slice_table

        trades = [
            {"timestamp": "2026-01-01T00:00:00+00:00", "r_multiple": 2.0, "direction": "BUY"},
            {"timestamp": "2026-01-01T01:00:00+00:00", "r_multiple": -1.0, "direction": "BUY"},
        ]
        rows = _slice_table(trades, lambda t: t["direction"])
        self.assertTrue(rows[0]["insufficient"])


class TestClassificationAndIsolation(unittest.TestCase):
    def test_unknown_costs_and_dead_medium_edge_is_c(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import book_metrics, classify_v41_after_costs

        oos = [2.0] * 1174 + [-1.0] * 2235  # ~3409, thin positive
        payload = {
            "cost_model_audit": {"historical_spread_tick_files": 0},
            "sensitivity_oos": {
                "zero": book_metrics(oos, cost_r=0.0),
                "low": book_metrics(oos, cost_r=0.01),
                "medium": book_metrics(oos, cost_r=0.03),
            },
            "labeled_assumption_scenarios": {
                "paper_round_trip": book_metrics(oos, cost_r=0.20),
            },
            "robustness": {"no_concentration_problem": False},
        }
        decision = classify_v41_after_costs(payload)
        self.assertEqual(decision["classification"], "C")
        self.assertTrue(decision["v41_remains_neutral_1_0"])
        self.assertFalse(decision["production_calibrators_modified"])

    def test_v41_stays_neutral(self) -> None:
        from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID, engine_calibration_factor
        from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics

        self.assertEqual(TREND_MODEL_ID, "trend_rf_v40")
        factor, label = engine_calibration_factor(engine="trend_rf_v41", regime="TREND", regime_strength=0.9)
        self.assertEqual(factor, 1.0)
        self.assertIn("neutral", label)
        self.assertEqual(HistoricalMetrics().engine_quality_factor("trend_rf_v41"), 1.0)

    def test_no_live_execution_imports(self) -> None:
        forbidden = {
            "tradingbot.live_runner",
            "tradingbot.execution.mt5_execution",
            "MetaTrader5",
            "scripts.start_bot",
        }
        for path in (PKG / "cost_robustness.py", PKG / "run_cost.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(imported & forbidden, path.name)

    def test_evidence_doc_exists_when_written(self) -> None:
        path = ROOT / "docs_v2" / "07_ml" / "V41_COST_ROBUSTNESS_EVIDENCE.md"
        if not path.is_file():
            self.skipTest("evidence doc not written yet")
        text = path.read_text(encoding="utf-8")
        self.assertIn("SENSITIVITY ANALYSIS", text)
        self.assertIn("UNKNOWN", text)
        self.assertIn("neutral 1.0", text)
        self.assertIn("C — insufficient evidence", text)
        self.assertIn("No v40 calibration factors were transferred", text)


if __name__ == "__main__":
    unittest.main()
