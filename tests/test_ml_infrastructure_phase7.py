"""Phase 7.0 production infrastructure tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.infrastructure.audit.audit_logger import AuditLogger, AuditRecord
from tradingbot.ml.infrastructure.config.runtime_config import RuntimeConfig, RuntimeConfigLoader
from tradingbot.ml.infrastructure.diagnostics.diagnostic_report import DiagnosticReportGenerator
from tradingbot.ml.infrastructure.health.health_checker import HealthChecker
from tradingbot.ml.infrastructure.health.schema import HealthStatus
from tradingbot.ml.infrastructure.recovery.recovery_manager import RecoveryManager, RecoveryMode
from tradingbot.ml.infrastructure.versioning.model_version import ModelVersionTracker

INFRA_PKG = ROOT / "tradingbot" / "ml" / "infrastructure"
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
        violations = _scan_package(INFRA_PKG)
        self.assertEqual(violations, [])

    def test_no_kernel_imports(self):
        for path in INFRA_PKG.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.kernel", text)

    def test_no_risk_imports(self):
        for path in INFRA_PKG.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.adapters.risk_gate", text)

    def test_no_execution_module_imports(self):
        for path in INFRA_PKG.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.execution", text)
            self.assertNotIn("tradingbot.adapters.mt5_execution", text)


class TestHealthChecks(unittest.TestCase):
    def test_health_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = HealthChecker(base_dir=tmp).check_all("XAUUSD", "M5")
            self.assertEqual(report.symbol, "XAUUSD")
            self.assertIn(report.overall_status, [s.value for s in HealthStatus])
            names = {c.name for c in report.components}
            self.assertIn("dataset", names)
            self.assertIn("monitoring", names)
            self.assertIn("deployment_gate", names)


class TestAuditLogger(unittest.TestCase):
    def test_audit_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = AuditLogger("XAUUSD", base_dir=tmp)
            record = AuditRecord(
                decision_timestamp="2024-03-01T10:00:00+00:00",
                model_version="1.0",
                feature_version="2.0",
                dataset_fingerprint="abc123",
                readiness_score=0.72,
                gate_state="CONDITIONAL_SHADOW",
                reasoning_chain=["ML bullish", "FINAL: BUY"],
            )
            logger.append(record)
            logger.append({**record.to_dict(), "decision_timestamp": "2024-03-01T11:00:00+00:00"})
            rows = logger.read_all()
            self.assertEqual(len(rows), 2)
            original = logger.path.read_text(encoding="utf-8")
            logger.append({**record.to_dict(), "decision_timestamp": "2024-03-01T12:00:00+00:00"})
            updated = logger.path.read_text(encoding="utf-8")
            self.assertTrue(updated.startswith(original))


class TestRecovery(unittest.TestCase):
    def test_recovery_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = RecoveryManager(base_dir=tmp).assess("XAUUSD", "M5")
            self.assertEqual(report.mode, RecoveryMode.SAFE_MODE.value)

            reports = Path(tmp) / "ml" / "reports"
            reports.mkdir(parents=True)
            (reports / "monitoring_summary.json").write_text(
                json.dumps({"model_health": "HEALTHY"}),
                encoding="utf-8",
            )
            report2 = RecoveryManager(base_dir=tmp, stale_hours=99999).assess("XAUUSD", "M5")
            self.assertIn(report2.mode, (RecoveryMode.DEGRADED.value, RecoveryMode.SAFE_MODE.value))

    def test_corrupted_report_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            deploy = Path(tmp) / "ml" / "deployment"
            deploy.mkdir(parents=True)
            (deploy / "readiness_report.json").write_text("{bad json", encoding="utf-8")
            report = RecoveryManager(base_dir=tmp).assess("XAUUSD", "M5")
            self.assertEqual(report.mode, RecoveryMode.FAILED.value)


class TestModelVersioning(unittest.TestCase):
    def test_model_version_tracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ModelVersionTracker(base_dir=tmp)
            record = tracker.collect("XAUUSD", "M5", "xgboost")
            self.assertEqual(record.symbol, "XAUUSD")
            tracker.write_registry([record])
            registry = tracker.read_registry()
            self.assertEqual(len(registry.get("models", [])), 1)


class TestConfigSafety(unittest.TestCase):
    def test_config_safety_defaults(self):
        cfg = RuntimeConfigLoader().defaults()
        self.assertTrue(cfg.shadow_mode)
        self.assertFalse(cfg.live_enabled)
        self.assertEqual(cfg.validate_safety(), [])

    def test_config_enforces_no_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = RuntimeConfigLoader(base_dir=tmp)
            cfg = RuntimeConfig(live_enabled=True, shadow_mode=False)
            loader.save(cfg)
            loaded = loader.load()
            self.assertTrue(loaded.shadow_mode)
            self.assertFalse(loaded.live_enabled)


class TestDiagnostics(unittest.TestCase):
    def test_diagnostic_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "ml" / "metadata"
            meta.mkdir(parents=True)
            (meta / "runtime_config.json").write_text(
                json.dumps({"active_model_name": "xgboost", "shadow_mode": True, "live_enabled": False}),
                encoding="utf-8",
            )
            report = DiagnosticReportGenerator(base_dir=tmp).generate("XAUUSD", "M5")
            self.assertIn("system", report)
            self.assertFalse(report["live_enabled"])
            self.assertTrue(report["shadow_mode"])
            self.assertIn("packages", report)

    def test_diagnostic_no_lookahead(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = DiagnosticReportGenerator(base_dir=tmp).generate("XAUUSD", "M5")
            serialized = json.dumps(report)
            self.assertNotIn("future_return", serialized)
            self.assertNotIn("tp_hit", serialized)

    def test_deterministic_health_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = HealthChecker(base_dir=tmp).check_all("XAUUSD", "M5")
            r2 = HealthChecker(base_dir=tmp).check_all("XAUUSD", "M5")
            self.assertEqual(r1.overall_status, r2.overall_status)
            self.assertEqual(len(r1.components), len(r2.components))


if __name__ == "__main__":
    unittest.main()
