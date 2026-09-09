"""Phase 111 multisource alignment tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase107_tick_intrabar_research import PHASE107_JSON, run_phase107_collection
from tradingbot.backtest.phase108_spread_path_research import PHASE108_JSON, run_phase108_collection
from tradingbot.backtest.phase109_htf_context_research import PHASE109_JSON, run_phase109_collection
from tradingbot.backtest.phase110_news_context_research import PHASE110_JSON, run_phase110_collection
from tradingbot.backtest.phase111_multisource_alignment import (
    PHASE,
    PHASE40_JSON,
    PHASE111_JSON,
    PHASE111_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase111_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE107_JSON).is_file():
        run_phase107_collection(root)
    if not (root / PHASE108_JSON).is_file():
        run_phase108_collection(root)
    if not (root / PHASE109_JSON).is_file():
        run_phase109_collection(root)
    if not (root / PHASE110_JSON).is_file():
        run_phase110_collection(root)
    art = root / PHASE111_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("brute_force_combinations") is False:
            return
    run_phase111_collection(root)


class TestPhase111(unittest.TestCase):
    def test_no_brute_force(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE111_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["brute_force_combinations"])
        self.assertTrue(payload["declared_before_evaluation"])
        self.assertFalse(payload["grid_search"])
        srcs = payload["source_status"]
        if srcs.get("tick") == "DATA_MISSING" and srcs.get("spread") == "DATA_MISSING" and srcs.get("news") == "DATA_MISSING":
            self.assertEqual(payload["n_declared"], 0)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE111_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase111_multisource_alignment.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("MULTISOURCE_DISCRIMINATOR_STATUS", (root / PHASE111_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
