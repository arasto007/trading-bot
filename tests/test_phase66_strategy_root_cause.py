"""Phase 66 root-cause tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase64_strategy_event_forensics import PHASE64_JSON, run_phase64_collection
from tradingbot.backtest.phase65_diagnostic_experiments import PHASE65_JSON, run_phase65_collection
from tradingbot.backtest.phase66_strategy_root_cause import (
    PHASE,
    PHASE66_JSON,
    PHASE66_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase66_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE64_JSON).is_file():
        run_phase64_collection(root)
    if not (root / PHASE65_JSON).is_file():
        run_phase65_collection(root)
    art = root / PHASE66_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase66_collection(root)


class TestPhase66(unittest.TestCase):
    def test_tree_and_primary(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE66_JSON).read_text(encoding="utf-8"))
        names = [c["name"] for c in payload["tree"]["STRATEGY_FRAGILITY"]["children"]]
        for required in (
            "ENTRY QUALITY",
            "EXIT BEHAVIOR",
            "REGIME DEPENDENCY",
            "TIME DEPENDENCY",
            "SIDE DEPENDENCY",
            "SIGNAL DUPLICATION",
            "OUTLIER DEPENDENCY",
            "COST SENSITIVITY",
            "DATA / EXECUTION",
        ):
            self.assertIn(required, names)
        self.assertEqual(payload["PRIMARY_ROOT_CAUSE"], "EXIT_PROBLEM")
        self.assertFalse(payload["parameters_optimized"])
        self.assertIn("EXIT BEHAVIOR", (root / PHASE66_MD).read_text(encoding="utf-8"))

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE66_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase66_strategy_root_cause.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()
