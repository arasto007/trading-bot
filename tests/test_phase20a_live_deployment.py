"""Phase 20A — live deployment tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase20a.config import (
    VERDICT_STARTED,
    DeploymentConfig,
    apply_certified_env,
    is_live_execution_enabled,
    reports_dir,
)
from tradingbot.ml.phase20a.rollback import execute_rollback
from tradingbot.ml.phase20a.reporter import Phase20aReporter
from tradingbot.ml.phase20a.safety_monitor import Phase20aSafetyMonitor


class TestConfig(unittest.TestCase):
    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase20a")

    def test_risk_clamped(self):
        cfg = DeploymentConfig(risk_pct=0.10)
        self.assertLessEqual(cfg.risk_pct, 0.05)

    def test_apply_env(self):
        cfg = DeploymentConfig()
        apply_certified_env(cfg)
        self.assertEqual(os.environ.get("TREND_MODEL_VERSION"), "v41")
        self.assertEqual(os.environ.get("USE_ML_KERNEL"), "true")


class TestRollback(unittest.TestCase):
    def test_rollback_env(self):
        rb = execute_rollback(reason="test")
        self.assertTrue(rb["rollback"])
        self.assertEqual(os.environ.get("TREND_MODEL_VERSION"), "v40")
        self.assertEqual(os.environ.get("ENABLE_RSI_FILTER"), "false")


class TestReporter(unittest.TestCase):
    def test_flush(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Phase20aReporter(base_dir=tmp)
            r.log_trade({"ticket": 1})
            paths = r.flush_all()
            self.assertTrue(Path(paths["live_trades"]).is_file())


class TestSafety(unittest.TestCase):
    def test_signal_explosion(self):
        s = Phase20aSafetyMonitor(DeploymentConfig())
        for _ in range(35):
            s.record_signal()
        self.assertTrue(s.should_stop)


class TestCertificationGate(unittest.TestCase):
    def test_verify_with_mock_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tradingbot.ml.data.paths import reports_dir as _r

            d = _r(tmp) / "phase19d"
            d.mkdir(parents=True)
            (d / "phase19d_final_report.json").write_text(
                json.dumps({"verdict": "APPROVED_FOR_FULL_PRODUCTION", "all_gates_pass": True}),
                encoding="utf-8",
            )
            from tradingbot.ml.phase20a.certification_gate import verify_certification

            result = verify_certification(base_dir=tmp)
            self.assertTrue(result["passed"])


class TestLiveEnable(unittest.TestCase):
    def test_not_enabled_by_default(self):
        os.environ.pop("ENABLE_PHASE20A_LIVE", None)
        os.environ.pop("PHASE20A_APPROVAL", None)
        self.assertFalse(is_live_execution_enabled())

    def test_enabled_with_flags(self):
        os.environ["ENABLE_PHASE20A_LIVE"] = "true"
        os.environ["PHASE20A_APPROVAL"] = "true"
        try:
            self.assertTrue(is_live_execution_enabled())
        finally:
            os.environ.pop("ENABLE_PHASE20A_LIVE", None)
            os.environ.pop("PHASE20A_APPROVAL", None)


class TestVerdict(unittest.TestCase):
    def test_verdict_constant(self):
        self.assertEqual(VERDICT_STARTED, "LIVE_DEPLOYMENT_STARTED")


if __name__ == "__main__":
    unittest.main()
