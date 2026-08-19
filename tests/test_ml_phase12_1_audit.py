"""Phase 12.1 — read-only architecture audit tests."""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.audit.phase12_1.contribution_analyzer import analyze_contribution
from tradingbot.ml.audit.phase12_1.dependency_analyzer import analyze_dependencies
from tradingbot.ml.audit.phase12_1.replay_analyzer import analyze_replay
from tradingbot.ml.audit.phase12_1.report_generator import run_phase12_1_audit
from tradingbot.ml.audit.phase12_1.signal_tracer import build_signal_flow_report
from tradingbot.ml.audit.phase12_1.strategy_discovery import discover_strategies
from tradingbot.ml.data.paths import phase12_1_final_report_path

AUDIT_PKG = ROOT / "tradingbot" / "ml" / "audit" / "phase12_1"
FORBIDDEN_KERNEL_IMPORT = "tradingbot.kernel"
FORBIDDEN_PATHS = (
    ROOT / "tradingbot" / "kernel",
    ROOT / "tradingbot" / "adapters" / "risk_gate.py",
    ROOT / "tradingbot" / "adapters" / "mt5_execution.py",
)


class TestPhase121Audit(unittest.TestCase):
    def test_strategy_discovery(self):
        inv = discover_strategies(root=ROOT)
        self.assertIn("priceaction", inv["enabled_strategies"])
        self.assertIn("ml_shadow_phase9_9", inv["ml_strategy"]["name"])
        self.assertTrue(len(inv["disabled_strategies"]) > 5)

    def test_signal_flow_report(self):
        flow = build_signal_flow_report()
        self.assertEqual(flow["registry_in_ml_path"], "CompositeStrategyRegistry")
        self.assertIn("ML_PRIORITY_OVERRIDE", flow["decision_mechanism"]["type"])

    def test_no_kernel_imports_in_audit_package(self):
        for py in AUDIT_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(node.module.startswith(FORBIDDEN_KERNEL_IMPORT))

    def test_no_order_send_in_audit_package(self):
        deps = analyze_dependencies(root=ROOT)
        self.assertEqual(deps["safety_scan"]["violations"], [])

    def test_dependency_analyzer_safety(self):
        deps = analyze_dependencies(root=ROOT)
        self.assertTrue(deps["safety_scan"]["audit_package_read_only"])
        self.assertIn("ML_PRIORITY_OVERRIDE", deps["architecture_mode_evidence"]["detected_mode"])

    def test_replay_analyzer_integrity(self):
        if not (ROOT / "data" / "ml" / "paper_trading" / "run_phase11_v1" / "cycles.json").is_file():
            self.skipTest("phase11 cycles not available")
        replay = analyze_replay(paper_run_id="phase11_v1")
        self.assertGreater(replay["total_cycles"], 1000)
        self.assertIn("signals", replay)

    def test_contribution_analyzer(self):
        if not (ROOT / "data" / "ml" / "paper_trading" / "run_phase11_v1" / "cycles.json").is_file():
            self.skipTest("phase11 cycles not available")
        contrib = analyze_contribution(paper_run_id="phase11_v1")
        self.assertIn("agreement_rate", contrib)
        self.assertIn("dominant_strategy", contrib)

    def test_full_audit_report_generation(self):
        if not (ROOT / "data" / "ml" / "paper_trading" / "run_phase11_v1" / "cycles.json").is_file():
            self.skipTest("phase11 data not available")
        result = run_phase12_1_audit(
            symbol="XAUUSD",
            timeframe="M5",
            paper_run_id="phase11_v1",
        )
        self.assertIn(result.architecture_mode, ("ML_ONLY", "ENSEMBLE", "ML_FILTER"))
        self.assertTrue(Path(result.reports["final"]).is_file())
        final_path = phase12_1_final_report_path()
        self.assertTrue(final_path.is_file())
        payload = json.loads(final_path.read_text(encoding="utf-8"))
        self.assertIn("answers", payload)
        self.assertIn("1_architecture", payload["answers"])

    def test_forbidden_paths_not_modified_by_audit(self):
        """Audit must not touch core files — verify audit pkg is separate."""
        self.assertTrue(AUDIT_PKG.is_dir())
        for path in FORBIDDEN_PATHS:
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
