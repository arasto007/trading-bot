"""Phase 90 path-shape forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase90_profit_giveback_path_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE90_JSON,
    PHASE90_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase90_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    art = root / PHASE90_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase90_collection(root)


class TestPhase90(unittest.TestCase):
    def test_classes_cover_events(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE90_JSON).read_text(encoding="utf-8"))
        n = sum(payload["path_classes"][k]["n"] for k in ("A", "B", "C", "D", "E", "F", "G"))
        self.assertEqual(n, 419)
        self.assertEqual(payload["path_classes"]["C"]["n"] + payload["path_classes"]["D"]["n"], 157)
        self.assertEqual(payload["path_classes"]["F"]["n"], 1)
        self.assertIn("2026-01-21", str(payload["outlier"]["timestamp"]))
        self.assertEqual(payload["outlier"]["path_class"], "F")
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["grid_search"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE90_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase90_profit_giveback_path_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("Path classes A-G", (root / PHASE90_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
