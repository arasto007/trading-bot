"""Phase 27.25 — targeted canonical Bid/Ask coverage tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.backtest.historical_bidask import CANONICAL_SYMBOL
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_25_canonical_bidask_coverage import (
    BLOCKED,
    BLOCKED_PENDING_DATA,
    FULL_CANONICAL_COVERAGE,
    NO_CANONICAL_COVERAGE,
    PARTIAL,
    PARTIAL_CANONICAL_COVERAGE,
    PHASE2725_JSON,
    PHASE2725_MD,
    PRODUCTION_M5,
    PROVEN,
    PROVEN_FOR_CANONICAL_DATASET,
    classify_canonical_coverage,
    compare_coverage,
    historical_spread_status,
    inspect_canonical_dataset,
    run_phase27_25_collection,
)


FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "history_deals_get",
    "history_orders_get",
)


def setUpModule() -> None:
    run_phase27_25_collection(Path(__file__).resolve().parents[1])


class TestPhase2725CanonicalBidAskCoverage(unittest.TestCase):
    def test_canonical_dataset_read_from_file(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inspected = inspect_canonical_dataset(root)
        self.assertTrue(inspected["exists"])
        self.assertEqual(inspected["path"], PRODUCTION_M5)
        self.assertEqual(inspected["symbol"], CANONICAL_SYMBOL)
        self.assertEqual(inspected["rows"], 3000)
        self.assertEqual(inspected["start_utc"], "2026-08-13T20:20:00Z")
        self.assertEqual(inspected["end_utc"], "2026-08-28T17:25:00Z")
        self.assertEqual(inspected["timezone"], "UTC")
        self.assertEqual(inspected["spread_mode"], "PROXY")
        self.assertFalse(inspected["has_bid_ask_columns"])
        payload = json.loads((root / PHASE2725_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["canonical_dataset"]["start_utc"], inspected["start_utc"])
        self.assertEqual(payload["canonical_dataset"]["end_utc"], inspected["end_utc"])
        self.assertEqual(payload["canonical_dataset"]["fingerprint"], inspected["fingerprint"])

    def test_full_coverage_requires_every_bar(self) -> None:
        self.assertEqual(
            classify_canonical_coverage(covered_bars=3000, dataset_bars=3000, collection_attempted=True),
            FULL_CANONICAL_COVERAGE,
        )
        self.assertEqual(
            classify_canonical_coverage(covered_bars=2999, dataset_bars=3000, collection_attempted=True),
            PARTIAL_CANONICAL_COVERAGE,
        )
        self.assertEqual(
            classify_canonical_coverage(covered_bars=0, dataset_bars=3000, collection_attempted=True),
            NO_CANONICAL_COVERAGE,
        )
        self.assertEqual(
            classify_canonical_coverage(covered_bars=0, dataset_bars=3000, collection_attempted=False),
            BLOCKED_PENDING_DATA,
        )
        self.assertEqual(historical_spread_status(FULL_CANONICAL_COVERAGE), PROVEN_FOR_CANONICAL_DATASET)
        self.assertEqual(historical_spread_status(PARTIAL_CANONICAL_COVERAGE), PARTIAL)
        self.assertEqual(historical_spread_status(NO_CANONICAL_COVERAGE), BLOCKED_PENDING_DATA)

    def test_compare_coverage_does_not_invent_full(self) -> None:
        ds = pd.DataFrame(
            {"open": [1, 2, 3]},
            index=pd.date_range("2026-08-13 20:20", periods=3, freq="5min", tz="UTC"),
        )
        ev = pd.DataFrame(
            {"bid": [1.0, 1.1], "ask": [1.2, 1.3]},
            index=pd.date_range("2026-08-13 20:20", periods=2, freq="5min", tz="UTC"),
        )
        cmp_ = compare_coverage(ds, ev)
        self.assertEqual(cmp_["covered_M5_bars"], 2)
        self.assertFalse(cmp_["canonical_fully_covered"])
        empty = compare_coverage(ds, None)
        self.assertEqual(empty["covered_M5_bars"], 0)
        self.assertFalse(empty["canonical_fully_covered"])

    def test_abcd_and_production_untouched(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2725_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.25")
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["abc"]["D_production_parquet_updated"])
        self.assertFalse(payload["production_parquet_updated"])
        self.assertTrue(payload["protected_production_untouched"])
        self.assertEqual(payload["canonical_dataset"]["spread_mode"], "PROXY")
        if payload["classification"] != FULL_CANONICAL_COVERAGE:
            self.assertEqual(payload["abc"]["C_canonical_dataset_fully_covered"], BLOCKED)
        self.assertFalse(payload["other_costs_collected"])

    def test_final_gate_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2725_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertFalse(payload["complete_costs_required_weakened"])
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["production_parquet_overwritten"])
        self.assertFalse(safety["proxy_converted_to_dataset"])
        self.assertFalse(safety["commission_collected"])
        self.assertFalse(safety["swap_collected"])
        self.assertFalse(safety["slippage_collected"])
        self.assertFalse(safety["execution_collected"])
        self.assertFalse(safety["phase_27_26_started"])
        text = (root / PHASE2725_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.25", text)
        self.assertIn("COMPLETE_COSTS_REQUIRED", text)

    def test_no_forbidden_source_tokens(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_25_canonical_bidask_coverage.py"
        ).read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        raw = (
            Path(__file__).resolve().parents[1] / PHASE2725_JSON
        ).read_text(encoding="utf-8").lower()
        self.assertNotIn("password", raw)


if __name__ == "__main__":
    unittest.main()
