"""Phase 45 — robustness tests on frozen Phase 40 artifacts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase44_executable_backtest_readiness import PHASE44_JSON, run_phase44_collection
from tradingbot.backtest.phase45_event_oos_regime_robustness import (
    ALLOWED_VERDICTS,
    PHASE,
    PHASE45_JSON,
    PHASE45_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase45_collection,
)

FORBIDDEN = (
    "from tradingbot.config.live",
    "run_phase40_collection(",
    "load_dotenv",
    "order_send(",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE44_JSON).is_file():
        run_phase44_collection(root)
    artifact = root / PHASE45_JSON
    if artifact.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("robustness_verdict") in ALLOWED_VERDICTS:
            return
    run_phase45_collection(root)


class TestPhase45Robustness(unittest.TestCase):
    def test_frozen_event_oos_fragile(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE45_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["events"]["event_count"], 420)
        self.assertAlmostEqual(payload["events"]["event_expectancy_R"], 0.04866, places=4)
        self.assertEqual(payload["oos"]["oos_signals"], 367)
        self.assertEqual(payload["oos"]["oos_events"], 63)
        self.assertFalse(payload["oos"]["boundaries_changed"])
        self.assertFalse(payload["oos"]["statistically_validated"])
        self.assertFalse(payload["phase40_scan_rerun"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertTrue(payload["dependence"]["do_not_treat_2847_as_iid"])
        self.assertFalse(payload["cost_aware"]["validated"])
        self.assertFalse(payload["cost_aware"]["executable_ran"])
        self.assertIn(payload["robustness_verdict"], ALLOWED_VERDICTS)
        self.assertEqual(payload["robustness_verdict"], "FRAGILE")
        self.assertNotEqual(payload["robustness_verdict"], "ROBUST")
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE45_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        src = (root / "tradingbot/backtest/phase45_event_oos_regime_robustness.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("ROBUSTNESS_VERDICT", (root / PHASE45_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
