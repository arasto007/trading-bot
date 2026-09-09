"""Phase 44 — fail-closed executable readiness tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase44_executable_backtest_readiness import (
    PHASE,
    PHASE44_JSON,
    PHASE44_MD,
    REQUIRED_ARTIFACT_KEYS,
    build_cost_inputs,
    evaluate_executable_readiness,
    is_verified_status,
    run_frozen_executable_if_ready,
    run_phase44_collection,
)

FORBIDDEN = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "from tradingbot.config.live",
    "run_phase40_collection(",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = root / PHASE44_JSON
    if artifact.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("EXECUTABLE_READY") is False and (root / PHASE44_MD).is_file():
            return
    run_phase44_collection(root)


class TestPhase44ExecutableReadiness(unittest.TestCase):
    def test_fail_closed_unknown_commission(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE44_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["EXECUTABLE_READY"])
        self.assertEqual(payload["EXECUTABLE_RESULT"], "BLOCKED")
        self.assertIsNone(payload["NET_EXPECTANCY"])
        self.assertFalse(payload["executable"]["ran"])
        self.assertFalse(payload["executable"]["fills_fabricated"])
        self.assertFalse(payload["executable"]["simulated_broker_invoked"])
        self.assertEqual(payload["cost_inputs"]["commission"]["evidence_status"], "UNKNOWN")
        self.assertFalse(is_verified_status("UNKNOWN"))
        self.assertFalse(is_verified_status("OBSERVED_ZERO_NOT_PROVEN"))
        self.assertFalse(is_verified_status("MODELED"))
        self.assertTrue(is_verified_status("VERIFIED_SCHEDULE"))
        fake = build_cost_inputs({}, {"commission": {"status": "UNKNOWN"}, "symbol": {"SYMBOL_MAPPING": "NOT_PROVEN"}})
        gate = evaluate_executable_readiness(fake)
        self.assertFalse(gate["EXECUTABLE_READY"])
        self.assertEqual(run_frozen_executable_if_ready(fake)["status"], "BLOCKED")

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE44_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["phase40_scan_rerun"])
        self.assertEqual(payload["production_safety"]["ENV"], "NOT_READ")
        src = (root / "tradingbot/backtest/phase44_executable_backtest_readiness.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("BLOCKED", (root / PHASE44_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
