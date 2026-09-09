"""Phase 1.5.46–1.5.50 — follow-up cost inventory, extended R-grid, rolling windows."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "tradingbot" / "ml" / "research" / "v41_isolated"


class TestExtendedSensitivityAndRolling(unittest.TestCase):
    def test_extended_grid_includes_required_costs(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import (
            EXTENDED_COST_GRID_R,
            extended_sensitivity,
        )

        self.assertEqual(EXTENDED_COST_GRID_R, (0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.08, 0.10))
        rs = [2.0] * 12 + [-1.0] * 20
        grid = extended_sensitivity(rs)
        for c in EXTENDED_COST_GRID_R:
            self.assertIn(f"{c:.2f}R", grid)
            self.assertTrue(grid[f"{c:.2f}R"]["not_measured_broker_cost"])
        self.assertGreater(grid["0.00R"]["expectancy"], grid["0.04R"]["expectancy"])

    def test_rolling_insufficient_when_short(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import rolling_trade_windows

        out = rolling_trade_windows([2.0, -1.0, 2.0], window=250)
        self.assertEqual(out["status"], "INSUFFICIENT")

    def test_rolling_reports_frac_positive(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import rolling_trade_windows

        rs = ([2.0] * 20 + [-1.0] * 20) * 8  # 320 trades
        out = rolling_trade_windows(rs, window=40)
        self.assertEqual(out["status"], "OK")
        self.assertIn("frac_positive", out["expectancy"])
        self.assertIn("note", out)


class TestPhase50Classification(unittest.TestCase):
    def test_four_cent_r_and_no_tape_is_c(self) -> None:
        from tradingbot.ml.research.v41_isolated.cost_robustness import book_metrics, classify_phase50

        oos = [2.0] * 1174 + [-1.0] * 2235
        payload = {
            "extended_sensitivity_oos": {
                "0.00R": book_metrics(oos, cost_r=0.0),
                "0.03R": book_metrics(oos, cost_r=0.03),
                "0.04R": book_metrics(oos, cost_r=0.04),
            },
            "cost_model_audit": {"historical_spread_tick_files": 0},
            "measured_live_entry_slippage": {"n": 17},
            "robustness": {"stability_verdict": "concentrated_and_disappears_under_modest_costs"},
        }
        decision = classify_phase50(payload)
        self.assertEqual(decision["classification"], "C")
        self.assertTrue(decision["v41_remains_neutral_1_0"])
        self.assertFalse(decision["production_calibrators_modified"])

    def test_v41_stays_neutral(self) -> None:
        from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID, engine_calibration_factor
        from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics

        self.assertEqual(TREND_MODEL_ID, "trend_rf_v40")
        factor, _ = engine_calibration_factor(engine="trend_rf_v41", regime="TREND", regime_strength=0.9)
        self.assertEqual(factor, 1.0)
        self.assertEqual(HistoricalMetrics().engine_quality_factor("trend_rf_v41"), 1.0)

    def test_no_live_imports(self) -> None:
        forbidden = {"tradingbot.live_runner", "MetaTrader5", "scripts.start_bot"}
        for name in ("cost_inventory.py", "run_followup.py", "cost_robustness.py"):
            tree = ast.parse((PKG / name).read_text(encoding="utf-8"), filename=name)
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(imported & forbidden, name)

    def test_docs_exist(self) -> None:
        audit = ROOT / "docs_v2" / "07_ml" / "V41_COST_EVIDENCE_AUDIT.md"
        rob = ROOT / "docs_v2" / "07_ml" / "V41_ROBUSTNESS_EVIDENCE.md"
        self.assertTrue(audit.is_file())
        self.assertTrue(rob.is_file())
        a = audit.read_text(encoding="utf-8")
        r = rob.read_text(encoding="utf-8")
        self.assertIn("UNKNOWN", a)
        self.assertIn("INSUFFICIENT", a)
        self.assertIn("17", a)
        self.assertIn("C — insufficient evidence", r)
        self.assertIn("0.04", r)
        self.assertIn("neutral 1.0", r)


if __name__ == "__main__":
    unittest.main()
