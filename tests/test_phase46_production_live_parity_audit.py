"""Phase 46 — live-parity audit tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase44_executable_backtest_readiness import PHASE44_JSON, run_phase44_collection
from tradingbot.backtest.phase45_event_oos_regime_robustness import PHASE45_JSON, run_phase45_collection
from tradingbot.backtest.phase46_production_live_parity_audit import (
    PHASE,
    PHASE46_BLOCKERS_MD,
    PHASE46_JSON,
    PHASE46_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase46_collection,
)

FORBIDDEN = (
    "from tradingbot.config.live",
    "run_phase40_collection(",
    "symbol_select(",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE44_JSON).is_file():
        run_phase44_collection(root)
    if not (root / PHASE45_JSON).is_file():
        run_phase45_collection(root)
    artifact = root / PHASE46_JSON
    if artifact.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("production_readiness") == "NOT_READY":
            return
    run_phase46_collection(root)


class TestPhase46Parity(unittest.TestCase):
    def test_not_ready_and_unresolved_cx(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE46_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["production_readiness"], "NOT_READY")
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")
        self.assertFalse(payload["verdict"]["ready_for_live"])
        self.assertEqual(payload["parity"]["EXECUTION_PARITY"]["status"], "FAIL")
        self.assertEqual(payload["parity"]["BROKER_PARITY"]["status"], "FAIL")
        ids = {c["id"] for c in payload["contradictions"]}
        self.assertIn("CX-REAL-SYMBOL", ids)
        self.assertIn("UNK-COMMISSION", ids)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["phase40_scan_rerun"])

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE46_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        src = (root / "tradingbot/backtest/phase46_production_live_parity_audit.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("NOT_READY", (root / PHASE46_MD).read_text(encoding="utf-8"))
        self.assertIn("Commission", (root / PHASE46_BLOCKERS_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
