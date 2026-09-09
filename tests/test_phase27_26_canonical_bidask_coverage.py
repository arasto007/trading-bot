"""Phase 27.26 — complete canonical Bid/Ask coverage tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.backtest.historical_bidask import CANONICAL_SYMBOL
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_25_canonical_bidask_coverage import (
    BLOCKED_PENDING_DATA,
    FULL_CANONICAL_COVERAGE,
    NO_CANONICAL_COVERAGE,
    PARTIAL_CANONICAL_COVERAGE,
    PRODUCTION_M5,
    TAPE_PARQUET as PHASE2725_TAPE,
    classify_canonical_coverage,
    compare_coverage,
    environment_matches,
    inspect_canonical_dataset,
    uncovered_intervals,
)
from tradingbot.backtest.phase27_26_canonical_bidask_coverage import (
    PHASE2726_JSON,
    PHASE2726_MD,
    REQUIRED_ARTIFACT_KEYS,
    TAPE_PARQUET,
    classify_gap_kind,
    historical_spread_status,
    merge_tick_frames,
    run_phase27_26_collection,
)


FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase27_26_collection(Path(__file__).resolve().parents[1])


class TestPhase2726CanonicalBidAskCoverage(unittest.TestCase):
    def test_canonical_dataset_range_discovery(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inspected = inspect_canonical_dataset(root)
        self.assertTrue(inspected["exists"])
        self.assertEqual(inspected["symbol"], CANONICAL_SYMBOL)
        self.assertEqual(inspected["rows"], 3000)
        self.assertEqual(inspected["start_utc"], "2026-08-13T20:20:00Z")
        self.assertEqual(inspected["end_utc"], "2026-08-28T17:25:00Z")
        payload = json.loads((root / PHASE2726_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_start_utc"], inspected["start_utc"])
        self.assertEqual(payload["dataset_end_utc"], inspected["end_utc"])
        self.assertEqual(payload["dataset_rows"], 3000)

    def test_coverage_and_gap_detection(self) -> None:
        ds = pd.DataFrame(
            {"open": [1, 2, 3, 4]},
            index=pd.date_range("2026-08-13 20:20", periods=4, freq="5min", tz="UTC"),
        )
        ev = pd.DataFrame(
            {"bid": [1.0, 1.1], "ask": [1.2, 1.3]},
            index=pd.date_range("2026-08-13 20:20", periods=2, freq="5min", tz="UTC"),
        )
        cmp_ = compare_coverage(ds, ev)
        self.assertEqual(cmp_["covered_M5_bars"], 2)
        self.assertFalse(cmp_["canonical_fully_covered"])
        gaps = uncovered_intervals(ds.index, ev.index)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["bars"], 2)

    def test_merge_dedup_does_not_fabricate(self) -> None:
        a = pd.DataFrame({"time": [1, 2], "bid": [10.0, 11.0], "ask": [10.2, 11.2]})
        b = pd.DataFrame({"time": [2, 3], "bid": [11.0, 12.0], "ask": [11.2, 12.2]})
        merged = merge_tick_frames(a, b)
        self.assertEqual(len(merged), 3)
        self.assertTrue((merged["ask"] >= merged["bid"]).all())
        incomplete = pd.DataFrame({"time": [4], "bid": [13.0]})
        merged2 = merge_tick_frames(a, incomplete)
        self.assertEqual(len(merged2), 2)
        self.assertNotIn(4, set(merged2["time"]))

    def test_classification_and_real_guard(self) -> None:
        self.assertEqual(
            classify_canonical_coverage(covered_bars=3000, dataset_bars=3000, collection_attempted=True),
            FULL_CANONICAL_COVERAGE,
        )
        self.assertEqual(
            classify_canonical_coverage(covered_bars=1680, dataset_bars=3000, collection_attempted=True),
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
        ok, _ = environment_matches({"trade_mode_label": "DEMO", "broker": "LiteFinance Global LLC", "server": "LiteFinance-MT5-Live"})
        self.assertFalse(ok)
        self.assertEqual(classify_gap_kind("2026-08-15T00:00:00Z", "2026-08-16T12:00:00Z", collected_through=None, stop_reason=None), "market_closure_weekend")
        self.assertEqual(historical_spread_status(FULL_CANONICAL_COVERAGE), "PROVEN_FOR_CANONICAL_DATASET")
        self.assertEqual(historical_spread_status(NO_CANONICAL_COVERAGE), "BLOCKED")

    def test_immutable_canonical_and_phase25_tape(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2726_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint_before"], payload["dataset_fingerprint_after"])
        self.assertFalse(payload["production_parquet_changed"])
        self.assertTrue((root / PHASE2725_TAPE).is_file())
        self.assertTrue(payload["tape"]["phase27_25_tape_preserved"])
        self.assertNotEqual(payload["tape"].get("path"), PHASE2725_TAPE)
        if payload.get("tape", {}).get("path"):
            self.assertEqual(payload["tape"]["path"], TAPE_PARQUET)
            self.assertTrue((root / TAPE_PARQUET).is_file())

    def test_artifact_schema_and_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2726_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["phase"], "27.26")
        self.assertIn(payload["status"], ("PASS", "PASS_WITH_DEFERRAL", "BLOCKED", "FAILED"))
        self.assertIn(
            payload["final_classification"],
            (FULL_CANONICAL_COVERAGE, PARTIAL_CANONICAL_COVERAGE, NO_CANONICAL_COVERAGE, BLOCKED_PENDING_DATA),
        )
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertFalse(payload["complete_costs_required_weakened"])

    def test_no_symbol_select_or_env(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_26_canonical_bidask_coverage.py"
        ).read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        raw = (Path(__file__).resolve().parents[1] / PHASE2726_JSON).read_text(encoding="utf-8").lower()
        self.assertNotIn("password", raw)
        text = (Path(__file__).resolve().parents[1] / PHASE2726_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.26", text)


if __name__ == "__main__":
    unittest.main()
