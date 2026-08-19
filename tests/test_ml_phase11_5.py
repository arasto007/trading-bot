"""Phase 11.5 — production readiness research tests."""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase11_5_final_report_path
from tradingbot.ml.research.phase11_5._metrics import scale_trades_risk, trade_metrics
from tradingbot.ml.research.phase11_5.optimizer_orchestrator import run_phase11_5_analysis, verify_safety
from tradingbot.ml.research.phase11_5.robustness_check import run_robustness_check
from tradingbot.ml.research.phase11_5.sell_bias_analyzer import analyze_sell_bias
from tradingbot.ml.research.phase11_5.threshold_optimizer import optimize_thresholds

PHASE11_5_PKG = ROOT / "tradingbot" / "ml" / "research" / "phase11_5"
FORBIDDEN_IMPORTS = ("tradingbot.kernel", "Mt5ExecutionAdapter", "order_send")


def _sample_trades() -> list[dict]:
    return [
        {"direction": "SELL", "ml_probability": 0.35, "R_multiple": 2.0, "pnl": 100.0, "atr": 4.0,
         "timestamp": "2026-06-01T08:00:00+00:00"},
        {"direction": "SELL", "ml_probability": 0.34, "R_multiple": -1.0, "pnl": -50.0, "atr": 5.0,
         "timestamp": "2026-06-01T14:00:00+00:00"},
        {"direction": "BUY", "ml_probability": 0.58, "R_multiple": 2.0, "pnl": 100.0, "atr": 3.0,
         "timestamp": "2026-06-01T20:00:00+00:00"},
        {"direction": "SELL", "ml_probability": 0.33, "R_multiple": -1.0, "pnl": -50.0, "atr": 6.0,
         "timestamp": "2026-06-02T07:00:00+00:00"},
    ]


def _sample_cycles() -> list[dict]:
    return [
        {"ml_probability": 0.35, "ml_signal": "SELL", "kernel_signal": "SELL"},
        {"ml_probability": 0.58, "ml_signal": "BUY", "kernel_signal": "BUY"},
        {"ml_probability": 0.50, "ml_signal": "HOLD", "kernel_signal": "NONE"},
        {"ml_probability": 0.34, "ml_signal": "SELL", "kernel_signal": "SELL"},
    ]


class TestPhase115(unittest.TestCase):
    def test_no_forbidden_imports_in_phase11_5(self):
        for py in PHASE11_5_PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_IMPORTS:
                self.assertNotIn(forbidden, text, msg=f"{py.name} references {forbidden}")

    def test_no_kernel_ast_in_research_package(self):
        for py in PHASE11_5_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(
                        node.module.startswith("tradingbot.kernel"),
                        msg=f"{py.name} imports {node.module}",
                    )

    def test_trade_metrics(self):
        m = trade_metrics(_sample_trades())
        self.assertEqual(m["trades"], 4)
        self.assertGreater(m["profit_factor"], 0)

    def test_threshold_optimizer_grid(self):
        result = optimize_thresholds(_sample_trades(), _sample_cycles())
        self.assertIn("grid", result)
        self.assertTrue(len(result["grid"]) > 0)
        self.assertIn("best_thresholds", result)

    def test_sell_bias_analyzer(self):
        result = analyze_sell_bias(_sample_trades(), _sample_cycles())
        self.assertIn("sell_trades_pct", result)
        self.assertIn("verdict", result)

    def test_risk_scaling(self):
        scaled = scale_trades_risk(_sample_trades(), 0.01)
        self.assertEqual(len(scaled), 4)
        self.assertEqual(scaled[0]["risk_percent"], 0.01)

    def test_robustness_check_iterations(self):
        result = run_robustness_check(_sample_trades(), iterations=100, seed=1)
        self.assertEqual(result["iterations"], 100)
        self.assertIn("bootstrap", result)
        self.assertIn("confidence_level", result)

    def test_full_analysis_on_production_data(self):
        if not (ROOT / "data" / "ml" / "paper_trading" / "run_phase11_v1" / "trades.json").is_file():
            self.skipTest("phase11_v1 paper data not available")
        result = run_phase11_5_analysis(
            symbol="XAUUSD",
            timeframe="M5",
            paper_run_id="phase11_v1",
            base_dir=ROOT,
            bootstrap_iterations=200,
        )
        self.assertIn(result.decision, ("READY_FOR_PHASE12", "NEEDS_MORE_RESEARCH"))
        self.assertTrue(Path(result.reports["final"]).is_file())
        final_path = phase11_5_final_report_path(ROOT)
        self.assertTrue(final_path.is_file())
        payload = json.loads(final_path.read_text(encoding="utf-8"))
        self.assertIn("findings", payload)
        self.assertIn("best_threshold", payload["findings"])

    def test_safety_verification(self):
        if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
            self.skipTest("phase9_9 artifacts not available")
        safety = verify_safety(base_dir=ROOT, paper_run_id="phase11_v1")
        self.assertTrue(safety["artifacts_readonly"])
        self.assertFalse(safety["execution_layer_touched"])
        self.assertTrue(safety.get("checksums_match_paper_run", False))


if __name__ == "__main__":
    unittest.main()
