"""Phase 67 next-research-gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase64_strategy_event_forensics import PHASE64_JSON, run_phase64_collection
from tradingbot.backtest.phase65_diagnostic_experiments import PHASE65_JSON, run_phase65_collection
from tradingbot.backtest.phase66_strategy_root_cause import PHASE66_JSON, run_phase66_collection
from tradingbot.backtest.phase67_next_research_gate import (
    ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE64_67_MD,
    PHASE67_JSON,
    PHASE67_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase67_collection,
    select_target,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE64_JSON).is_file():
        run_phase64_collection(root)
    if not (root / PHASE65_JSON).is_file():
        run_phase65_collection(root)
    if not (root / PHASE66_JSON).is_file():
        run_phase66_collection(root)
    art = root / PHASE67_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("OPTIMIZATION_ALLOWED") is False:
            return
    run_phase67_collection(root)


class TestPhase67(unittest.TestCase):
    def test_selects_exit_research_not_optimize_or_broker(self) -> None:
        nxt, _ = select_target(
            {"causes": {"PRIMARY": "EXIT_PROBLEM"}, "mae_mfe": {"losers_mfe_gt_0_5R": 157}},
            {"experiments": {"B_outlier_robustness": {"positive_expectancy_survives_top1_removed": False}}},
            {},
        )
        self.assertEqual(nxt, "EXIT_RESEARCH")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE67_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["NEXT_RESEARCH_TARGET"], ALLOWED)
        self.assertEqual(payload["NEXT_RESEARCH_TARGET"], "EXIT_RESEARCH")
        self.assertNotEqual(payload["NEXT_RESEARCH_TARGET"], "COST_RESEARCH")
        self.assertFalse(payload["OPTIMIZATION_ALLOWED"])
        self.assertFalse(payload["LIVE_TRADING_ALLOWED"])
        self.assertFalse(payload["broker_forensics_restarted"])
        self.assertFalse(payload["project_stopped"])
        self.assertIn("Optimization", payload["DO_NOT_DO_YET"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE67_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase67_next_research_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("WHY THE STRATEGY LOSES", (root / PHASE64_67_MD).read_text(encoding="utf-8"))
        self.assertIn("EXIT_RESEARCH", (root / PHASE67_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
