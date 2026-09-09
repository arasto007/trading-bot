"""Phase 73 exit research gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase68_exit_forensics import PHASE68_JSON, run_phase68_collection
from tradingbot.backtest.phase69_exit_geometry import PHASE69_JSON, run_phase69_collection
from tradingbot.backtest.phase70_exit_counterfactuals import PHASE70_JSON, run_phase70_collection
from tradingbot.backtest.phase71_extreme_winner_forensics import PHASE71_JSON, run_phase71_collection
from tradingbot.backtest.phase72_exit_root_cause import PHASE72_JSON, run_phase72_collection
from tradingbot.backtest.phase73_exit_research_gate import (
    ALLOWED,
    LEDGER_MD,
    PHASE,
    PHASE40_JSON,
    PHASE73_JSON,
    PHASE73_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase73_collection,
    select_target,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE68_JSON).is_file():
        run_phase68_collection(root)
    if not (root / PHASE69_JSON).is_file():
        run_phase69_collection(root)
    if not (root / PHASE70_JSON).is_file():
        run_phase70_collection(root)
    if not (root / PHASE71_JSON).is_file():
        run_phase71_collection(root)
    if not (root / PHASE72_JSON).is_file():
        run_phase72_collection(root)
    art = root / PHASE73_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("intervention_implemented") is False:
            return
    run_phase73_collection(root)


class TestPhase73(unittest.TestCase):
    def test_selects_profit_protection_spec_not_implemented(self) -> None:
        nxt, _ = select_target(
            {"LOSS_AFTER_0_5R": 157, "LOSS_AFTER_1R": 94, "lineage_meta": {"LOSS_SL": 298}, "mechanism_ranking": {"PRIMARY_MECHANISM": "C_PROFIT_PROTECTION"}},
            {"PRIMARY_CAUSE": "PROFIT_GIVEBACK"},
        )
        self.assertEqual(nxt, "PROFIT_PROTECTION_RESEARCH")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE73_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["NEXT_RESEARCH_TARGET"], ALLOWED)
        self.assertEqual(payload["NEXT_RESEARCH_TARGET"], "PROFIT_PROTECTION_RESEARCH")
        self.assertFalse(payload["intervention_implemented"])
        self.assertFalse(payload["OPTIMIZATION_ALLOWED"])
        self.assertFalse(payload["LIVE_TRADING_ALLOWED"])
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertEqual(payload["spec"]["variants_allowed"], 1)
        self.assertTrue(payload["spec"]["do_not_implement_in_phase73"])
        self.assertGreaterEqual(payload["HYPOTHESES_TESTED"], 15)
        self.assertTrue((root / LEDGER_MD).is_file())

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE73_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase73_exit_research_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("PROFIT_PROTECTION_RESEARCH", (root / PHASE73_MD).read_text(encoding="utf-8"))
        self.assertIn("H68-01", (root / LEDGER_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
