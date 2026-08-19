"""Phase 22H — active engine alignment tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.decision_engine.strategy_selector import select_engine
from tradingbot.ml.integration.health_gate import run_pre_decision_health
from tradingbot.ml.integration.recovered_calibration import calibration_status
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version


class TestPhase22HAlignment(unittest.TestCase):
    def setUp(self):
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ["TREND_MODEL_VERSION"] = "v41"

    def test_strategy_selector_uses_active_engine(self):
        self.assertEqual(select_engine("TREND"), resolve_active_trend_engine_id())

    def test_calibration_status_reports_active(self):
        status = calibration_status()
        self.assertEqual(status["active_trend_engine_id"], resolve_active_trend_engine_id())

    def test_health_gate_source_uses_version_resolver(self):
        src = (ROOT / "tradingbot" / "ml" / "integration" / "health_gate.py").read_text(encoding="utf-8")
        self.assertIn("resolve_bundle_version()", src)
        self.assertIn("resolve_active_trend_engine_id()", src)

    def test_recovered_calibration_no_hardcoded_v40(self):
        src = (ROOT / "tradingbot" / "ml" / "integration" / "recovered_calibration.py").read_text(encoding="utf-8")
        self.assertNotIn('get("trend_rf_v40")', src)
        self.assertIn("resolve_active_trend_engine_id()", src)

    def test_bundle_version_default_v41_env(self):
        self.assertEqual(resolve_bundle_version(), "v41")
        self.assertEqual(resolve_active_trend_engine_id(), "trend_rf_v41")


if __name__ == "__main__":
    unittest.main()
