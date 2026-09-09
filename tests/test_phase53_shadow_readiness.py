"""Phase 53 shadow-readiness tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase51_final_evidence_closure import PHASE51_JSON, run_phase51_collection
from tradingbot.backtest.phase52_optimization_gate import PHASE52_JSON, run_phase52_collection
from tradingbot.backtest.phase53_shadow_readiness import (
    PHASE,
    PHASE53_JSON,
    PHASE53_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase53_collection,
)
from tradingbot.backtest.shadow_observation import (
    ShadowActivationBlocked,
    ShadowFramework,
    ShadowObservation,
    ShadowOrderForbidden,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN_TAPE_FINGERPRINT = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE51_JSON).is_file():
        run_phase51_collection(root)
    if not (root / PHASE52_JSON).is_file():
        run_phase52_collection(root)
    art = root / PHASE53_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("SHADOW_ACTIVE") is False:
            return
    run_phase53_collection(root)


class TestPhase53(unittest.TestCase):
    def test_shadow_cannot_place_orders_or_activate(self) -> None:
        framework = ShadowFramework()
        self.assertFalse(framework.ACTIVE)
        with self.assertRaises(ShadowActivationBlocked):
            framework.activate()
        with self.assertRaises(ShadowOrderForbidden):
            framework.place_order(symbol="XAUUSD_i", volume=0.01)
        hypo = framework.hypothetical_fill(ShadowObservation(SYMBOL="XAUUSD_i", SIGNAL="BUY"))
        self.assertFalse(hypo["order_sent"])
        self.assertEqual(hypo["OUTCOME"], "HYPOTHETICAL_ONLY")

    def test_acceptance_blocked_and_not_activated(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE53_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["SHADOW_FRAMEWORK"], "SPECIFIED")
        self.assertFalse(payload["SHADOW_ACTIVE"])
        self.assertEqual(payload["ORDERS_PLACED"], 0)
        self.assertEqual(payload["ACCEPTANCE_GATE"], "BLOCKED")
        self.assertEqual(payload["RESULT"], "SPECIFIED_NOT_ACTIVATED")
        self.assertFalse(payload["framework"]["can_place_orders"])
        self.assertFalse(payload["framework"]["wired_into_live_loop"])
        self.assertFalse(payload["env_accessed"])

    def test_frozen_intact_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE53_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN_TAPE_FINGERPRINT)
        src = (root / "tradingbot/backtest/phase53_shadow_readiness.py").read_text(encoding="utf-8")
        spec = (root / "tradingbot/backtest/shadow_observation.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
            self.assertNotIn(token, spec)
        self.assertNotIn("def execute(", spec)
        self.assertIn("NOT_ACTIVATED", (root / PHASE53_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
