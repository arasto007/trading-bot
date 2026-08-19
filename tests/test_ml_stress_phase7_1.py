"""Phase 7.1 stress testing tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.stress.chaos_tests import (
    StressSandbox,
    simulate_extreme_drift,
    simulate_missing_features,
    simulate_model_failure,
    simulate_report_corruption,
)
from tradingbot.ml.stress.resilience import ResilienceEvaluator
from tradingbot.ml.stress.scenarios import ALL_SCENARIOS, FailureScenario, SCENARIO_CATALOG
from tradingbot.ml.stress.simulator import StressScenarioRunner

STRESS_PKG = ROOT / "tradingbot" / "ml" / "stress"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _scan_package(package_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in package_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            for module in mods:
                for prefix in FORBIDDEN:
                    if module.startswith(prefix):
                        violations.append(f"{path.relative_to(package_dir)}: {module}")
    return violations


class TestIsolation(unittest.TestCase):
    def test_forbidden_execution_imports(self):
        self.assertEqual(_scan_package(STRESS_PKG), [])


class TestScenarios(unittest.TestCase):
    def test_every_failure_scenario_defined(self):
        self.assertEqual(len(ALL_SCENARIOS), 12)
        for scenario in ALL_SCENARIOS:
            self.assertIn(scenario, SCENARIO_CATALOG)

    def test_every_scenario_runs_in_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = StressSandbox.create(Path(tmp))
            runner = StressScenarioRunner(stale_hours=1.0)
            for scenario in ALL_SCENARIOS:
                sandbox.seed_baseline()
                sandbox.restore_all()
                result = runner.run_scenario(sandbox, scenario)
                self.assertEqual(result.scenario, scenario.value)
                self.assertTrue(result.timestamp)


class TestChaosFunctions(unittest.TestCase):
    def test_chaos_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = StressSandbox.create(Path(tmp))
            self.assertTrue(simulate_missing_features(sandbox))
            sandbox.restore_all()
            sandbox.seed_baseline()
            self.assertTrue(simulate_model_failure(sandbox))
            sandbox.restore_all()
            sandbox.seed_baseline()
            self.assertTrue(simulate_report_corruption(sandbox))
            sandbox.restore_all()
            sandbox.seed_baseline()
            self.assertTrue(simulate_extreme_drift(sandbox))


class TestRecoveryAndDiagnostics(unittest.TestCase):
    def test_diagnostics_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = StressSandbox.create(Path(tmp))
            result = StressScenarioRunner(stale_hours=1.0).run_scenario(
                sandbox, FailureScenario.REPORT_CORRUPTION
            )
            self.assertTrue(result.detected)
            self.assertIn(result.recovery_mode, ("FAILED", "DEGRADED", "SAFE_MODE"))

    def test_recovery_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = StressSandbox.create(Path(tmp))
            results = StressScenarioRunner(stale_hours=1.0).run_all(sandbox)
            modes = {r.recovery_mode for r in results}
            self.assertTrue(len(modes) >= 1)


class TestSandboxSafety(unittest.TestCase):
    def test_no_data_destruction(self):
        with tempfile.TemporaryDirectory() as prod:
            prod_file = Path(prod) / "production_marker.txt"
            prod_file.write_text("do-not-touch", encoding="utf-8")
            with tempfile.TemporaryDirectory() as sandbox_root:
                sandbox = StressSandbox.create(Path(sandbox_root))
                for scenario in ALL_SCENARIOS:
                    sandbox.apply_scenario(scenario)
                    sandbox.restore_all()
            self.assertEqual(prod_file.read_text(encoding="utf-8"), "do-not-touch")

    def test_sandbox_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = StressSandbox.create(Path(tmp))
            feat = sandbox.apply_scenario(FailureScenario.MISSING_FEATURE_DATA)[0]
            self.assertFalse(feat.is_file())
            sandbox.restore_all()
            sandbox.seed_baseline()
            self.assertTrue(feat.is_file())


class TestResilience(unittest.TestCase):
    def test_resilience_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = StressSandbox.create(Path(tmp))
            results = StressScenarioRunner(stale_hours=1.0).run_all(sandbox)
            evaluator = ResilienceEvaluator(base_dir=tmp)
            metrics = evaluator.evaluate(results)
            path = evaluator.write_report(results, metrics)
            self.assertEqual(metrics.scenarios_tested, 12)
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("summary", payload)


if __name__ == "__main__":
    unittest.main()
