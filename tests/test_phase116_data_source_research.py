"""Phase 116 data source research tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE40_SETUPS_JSONL
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import EXPECTED_JSONL_SHA256, file_sha256
from tradingbot.backtest.phase116_data_source_research import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    CANONICAL_SYMBOL,
    GATE_CLASSES,
    N_EVENTS,
    OUTLIER_TS,
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE116_JSON,
    PHASE116_MD,
    REQUIRED_ARTIFACT_KEYS,
    acquisition_path_status,
    classify_chronology,
    classify_identity,
    coverage_bucket,
    full_horizon_covered,
    outlier_in_range,
    run_phase116_collection,
    substitution_verdict,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE116_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("DATA_ACQUIRED") is False:
            return
    run_phase116_collection(root)


class TestPhase116Helpers(unittest.TestCase):
    def test_identity_gate(self) -> None:
        self.assertEqual(classify_identity(exact_symbol="XAUUSD_i", proven_xauusd_i=True, generic=False), "VERIFIED_XAUUSD_I")
        self.assertEqual(classify_identity(exact_symbol="XAUUSD", proven_xauusd_i=False, generic=True), "GENERIC_XAUUSD")
        self.assertEqual(classify_identity(exact_symbol="GOLD", proven_xauusd_i=False, generic=True), "GENERIC_XAUUSD")
        self.assertEqual(classify_identity(exact_symbol="XAUUSD_i", proven_xauusd_i=False, generic=False), "XAUUSD_I_LIKELY_BUT_UNPROVEN")
        self.assertEqual(classify_identity(exact_symbol=None, proven_xauusd_i=False, generic=False), "UNKNOWN")

    def test_generic_xauusd_rejection(self) -> None:
        self.assertEqual(substitution_verdict("generic_XAUUSD"), "REJECTED")
        self.assertEqual(substitution_verdict("GOLD"), "REJECTED")
        self.assertEqual(substitution_verdict("OHLC_derived_ticks"), "REJECTED")
        self.assertEqual(substitution_verdict("synthetic_bid_ask"), "REJECTED")
        self.assertEqual(substitution_verdict("interpolated_ticks"), "REJECTED")
        self.assertEqual(substitution_verdict("tester_generated_ticks"), "REJECTED")
        self.assertEqual(substitution_verdict("futures_gold"), "RESEARCH-ONLY")
        self.assertEqual(substitution_verdict("another_broker_XAUUSD"), "RESEARCH-ONLY")

    def test_full_horizon_contract(self) -> None:
        self.assertEqual(ACQ_START_ISO, "2023-02-26T15:40:00Z")
        self.assertEqual(ACQ_END_ISO, "2026-09-07T20:10:00Z")
        self.assertTrue(full_horizon_covered("2003-05-05T00:01:03Z", "2026-09-07T20:10:00Z"))
        self.assertFalse(full_horizon_covered("2026-08-13T20:20:00Z", "2026-09-01T17:52:29Z"))
        self.assertFalse(full_horizon_covered(None, None))

    def test_outlier_inclusion(self) -> None:
        self.assertEqual(OUTLIER_TS, "2026-01-21T15:40:00Z")
        self.assertTrue(outlier_in_range("2003-05-05T00:01:03Z", "2026-09-07T20:10:00Z"))
        self.assertFalse(outlier_in_range("2026-08-13T20:20:00Z", "2026-09-01T17:52:29Z"))
        self.assertIsNone(outlier_in_range(None, None))

    def test_coverage_and_chronology_classes(self) -> None:
        self.assertEqual(coverage_bucket(419), "419/419 feasible")
        self.assertEqual(coverage_bucket(3), "<200 feasible")
        self.assertEqual(coverage_bucket(None, unknown=True), "UNKNOWN")
        self.assertEqual(classify_chronology(bid=True, ask=True, quote_updates=True, same_ms_preserved=True, ohlc_only=False, identity="VERIFIED_XAUUSD_I"), "STRONG")
        self.assertEqual(classify_chronology(bid=True, ask=True, quote_updates=True, same_ms_preserved=True, ohlc_only=False, identity="GENERIC_XAUUSD"), "MODERATE")
        self.assertEqual(classify_chronology(bid=False, ask=False, quote_updates=False, same_ms_preserved=False, ohlc_only=True, identity="VERIFIED_XAUUSD_I"), "INSUFFICIENT")

    def test_acquisition_gate(self) -> None:
        self.assertEqual(acquisition_path_status(verified_full_horizon=True, verified_method_unproven_coverage=True, verified_partial_local=True), "READY_EXACT_XAUUSD_I")
        self.assertEqual(acquisition_path_status(verified_full_horizon=False, verified_method_unproven_coverage=True, verified_partial_local=True), "READY_WITH_OPERATOR_ACTION")
        self.assertEqual(acquisition_path_status(verified_full_horizon=False, verified_method_unproven_coverage=False, verified_partial_local=True), "PARTIALLY_READY")
        self.assertEqual(acquisition_path_status(verified_full_horizon=False, verified_method_unproven_coverage=False, verified_partial_local=False), "NO_VALID_SOURCE_FOUND")
        for g in GATE_CLASSES:
            self.assertIsInstance(g, str)


class TestPhase116Collection(unittest.TestCase):
    def test_catalog_and_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE116_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["n_events"], N_EVENTS)
        self.assertEqual(payload["n_events"], 419)
        self.assertFalse(payload["DATA_ACQUIRED"])
        self.assertFalse(payload["downloaded"])
        self.assertFalse(payload["MT5_USED"])
        self.assertFalse(payload["ENV_ACCESSED"])
        self.assertFalse(payload["EXIT_DESIGN_SPEC_IMPLEMENTED"])
        self.assertEqual(payload["GENERIC_XAUUSD_STATUS"], "REJECTED")
        self.assertEqual(payload["ACQUISITION_PATH_STATUS"], "READY_WITH_OPERATOR_ACTION")
        self.assertIn(payload["ACQUISITION_PATH_STATUS"], GATE_CLASSES)
        names = [c["source_name"] for c in payload["candidates"]]
        self.assertIn("LITEFINANCE_MT5_SYMBOLS_TICKS_TAB_EXPORT", names)
        duk = next(c for c in payload["candidates"] if c["source_name"] == "DUKASCOPY_XAUUSD_TICKS")
        self.assertEqual(duk["identity_class"], "GENERIC_XAUUSD")
        self.assertFalse(duk["canonical_eligible"])
        local = next(c for c in payload["candidates"] if c["source_name"] == "LOCAL_XAUUSD_I_TICK_SIDECARS")
        self.assertEqual(local["identity_class"], "VERIFIED_XAUUSD_I")
        self.assertEqual(local["event_coverage_class"], "<200 feasible")
        self.assertFalse(payload["refined_contract"]["weakened_phase114"])
        self.assertEqual(payload["refined_contract"]["symbol"], CANONICAL_SYMBOL)
        opt_c = next(o for o in payload["acquisition_options"] if o["id"] == "OPTION_C")
        self.assertFalse(opt_c["valid"])
        ledger = (root / LEDGER_MD).read_text(encoding="utf-8")
        self.assertIn("H116-01", ledger)
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 116 started | **YES** |", ku)
        self.assertIn("| Phase 117 started | **YES** |", ku)
        self.assertIn("| Phase 118 started | **YES** |", ku)
        self.assertIn("| Phase 119 started | **YES** |", ku)
        self.assertIn("| Phase 120 started | **YES** |", ku)
        self.assertIn("| Phase 121 started | **YES** |", ku)
        self.assertIn("| Phase 122 started | **YES** |", ku)
        self.assertIn("| Phase 123 started | **YES** |", ku)
        self.assertIn("| Phase 124 started | **NO** |", ku)
        self.assertIn("PHASE116_STATUS", (root / PHASE116_MD).read_text(encoding="utf-8"))
        src = (root / "tradingbot/backtest/phase116_data_source_research.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertNotIn("mt5.initialize", src)

    def test_frozen_phase40(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE116_JSON).read_text(encoding="utf-8"))
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertEqual(file_sha256(root / PHASE40_SETUPS_JSONL), EXPECTED_JSONL_SHA256)
        self.assertEqual(payload["FROZEN_PHASE40_TIMESTAMP"], PHASE40_TS)
        self.assertEqual(payload["FROZEN_PHASE40_FINGERPRINT"], FROZEN)
        self.assertEqual(payload["FROZEN_PHASE40_SHA256"], EXPECTED_JSONL_SHA256)
        self.assertFalse(payload["frozen_integrity"]["repaired"])


if __name__ == "__main__":
    unittest.main()