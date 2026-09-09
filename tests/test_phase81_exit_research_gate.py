"""Phase 81 exit research gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase75_exit_counterfactuals import PHASE75_JSON, run_phase75_collection
from tradingbot.backtest.phase76_sl_vs_profit_protection import PHASE76_JSON, run_phase76_collection
from tradingbot.backtest.phase77_exit_geometry_forensics import PHASE77_JSON, run_phase77_collection
from tradingbot.backtest.phase78_time_exit_forensics import PHASE78_JSON, run_phase78_collection
from tradingbot.backtest.phase79_exit_side_regime import PHASE79_JSON, run_phase79_collection
from tradingbot.backtest.phase80_extreme_winner_audit import PHASE80_JSON, run_phase80_collection
from tradingbot.backtest.phase81_exit_research_gate import (
    NEXT_ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE81_JSON,
    PHASE81_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase81_collection,
    select,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    if not (root / PHASE75_JSON).is_file():
        run_phase75_collection(root)
    if not (root / PHASE76_JSON).is_file():
        run_phase76_collection(root)
    if not (root / PHASE77_JSON).is_file():
        run_phase77_collection(root)
    if not (root / PHASE78_JSON).is_file():
        run_phase78_collection(root)
    if not (root / PHASE79_JSON).is_file():
        run_phase79_collection(root)
    if not (root / PHASE80_JSON).is_file():
        run_phase80_collection(root)
    art = root / PHASE81_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("intervention_implemented") is False:
            return
    run_phase81_collection(root)


class TestPhase81(unittest.TestCase):
    def test_selects_protection_design_not_implemented(self) -> None:
        primary, _s, _t, nxt = select(
            {"PROFIT_GIVEBACK_RATE": 0.9, "LOSS_AFTER_1R": 94},
            {"BEST_STRUCTURAL_COUNTERFACTUAL_STATUS": "HELPFUL"},
            {"verdict": {"primary": "SL_ACCEPTABLE_BUT_NO_PROFIT_PROTECTION"}},
            {"TIME_DEPENDENCY": "SECONDARY"},
            {},
        )
        self.assertEqual(primary, "PROFIT_GIVEBACK")
        self.assertEqual(nxt, "PROFIT_PROTECTION_DESIGN")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE81_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["NEXT_RESEARCH_TARGET"], NEXT_ALLOWED)
        self.assertEqual(payload["NEXT_RESEARCH_TARGET"], "PROFIT_PROTECTION_DESIGN")
        self.assertEqual(payload["PRIMARY_EXIT_MECHANISM"], "PROFIT_GIVEBACK")
        self.assertFalse(payload["intervention_implemented"])
        self.assertFalse(payload["OPTIMIZATION_ALLOWED"])
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertTrue((root / LEDGER_MD).is_file())
        self.assertIn("H74-01", (root / LEDGER_MD).read_text(encoding="utf-8"))

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE81_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase81_exit_research_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("PROFIT_PROTECTION_DESIGN", (root / PHASE81_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
