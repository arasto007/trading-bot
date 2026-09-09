"""Phase 52 optimization-gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.optimization_gate import (
    evaluate_optimization_gate,
    fragile_robustness_blocks_optimization,
)
from tradingbot.backtest.phase51_final_evidence_closure import PHASE51_JSON, run_phase51_collection
from tradingbot.backtest.phase52_optimization_gate import (
    PHASE,
    PHASE40_JSON,
    PHASE52_JSON,
    PHASE52_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase52_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN_TAPE_FINGERPRINT = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE51_JSON).is_file():
        run_phase51_collection(root)
    art = root / PHASE52_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("OPTIMIZATION_EXECUTED") is False:
            return
    run_phase52_collection(root)


class TestPhase52(unittest.TestCase):
    def test_fragile_and_broker_blockers_block_optimization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE52_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["OPTIMIZATION_GATE"], "BLOCKED")
        self.assertFalse(payload["OPTIMIZATION_EXECUTED"])
        self.assertTrue(payload["BASELINE_PRESERVED"])
        self.assertIn("commission_verified", payload["CONDITIONS_FAILED"])
        self.assertIn("robustness_not_fragile", payload["CONDITIONS_FAILED"])
        self.assertIn("no_material_unresolved_blocker", payload["CONDITIONS_FAILED"])
        self.assertTrue(fragile_robustness_blocks_optimization("FRAGILE"))
        self.assertFalse(payload["parameters_searched"])
        self.assertFalse(payload["genetic"])

    def test_gate_function_fail_closed(self) -> None:
        gate = evaluate_optimization_gate(
            commission_verified=False,
            symbol_equivalence_verified=False,
            executable_completed=False,
            net_expectancy_R=None,
            event_net_expectancy_R=None,
            oos_net_expectancy_R=None,
            oos_sample_sufficient=True,
            bootstrap_obviously_fragile=True,
            recent_materially_contradictory=True,
            production_parity_fail=True,
            material_unresolved_blocker=True,
            robustness_verdict="FRAGILE",
            evidence_margin_exceeds_cost_uncertainty=False,
        )
        self.assertEqual(gate["OPTIMIZATION_GATE"], "BLOCKED")
        self.assertFalse(gate["optimization_allowed"])
        self.assertGreaterEqual(gate["conditions_failed"], 10)

    def test_frozen_intact_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE52_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN_TAPE_FINGERPRINT)
        src = (root / "tradingbot/backtest/phase52_optimization_gate.py").read_text(encoding="utf-8")
        gate_src = (root / "tradingbot/backtest/optimization_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
            self.assertNotIn(token, gate_src)
        self.assertFalse(payload["env_accessed"])
        self.assertIn("BLOCKED", (root / PHASE52_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
