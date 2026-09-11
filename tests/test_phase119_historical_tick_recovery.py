"""Phase 119 historical tick recovery source-resolution tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE40_SETUPS_JSONL
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    file_sha256,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS, substitution_verdict
from tradingbot.backtest.phase118_tick_forensic_validation import EXPECTED_RAW_SHA256
from tradingbot.backtest.phase119_historical_tick_recovery import (
    MISSING_END,
    MISSING_START,
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE119_JSON,
    PHASE119_MD,
    run_phase119_collection,
    source_catalog,
    support_request_template,
)

FORBIDDEN = (
    "from tradingbot.config.live",
    "run_phase40_collection(",
    "symbol_select(",
    "mt5.initialize",
    "copy_ticks_range(",
)
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE119_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("DATA_ACQUIRED") is False
            and payload.get("MT5_USED") is False
        ):
            return
    run_phase119_collection(root)


class TestPhase119Helpers(unittest.TestCase):
    def test_identity_and_generic_rejection(self) -> None:
        self.assertTrue(verify_xauusd_i(symbol="XAUUSD_i"))
        self.assertFalse(verify_xauusd_i(symbol="XAUUSD"))
        self.assertEqual(substitution_verdict("generic_XAUUSD"), "REJECTED")
        self.assertEqual(substitution_verdict("tester_generated_ticks"), "REJECTED")

    def test_missing_window_and_outlier(self) -> None:
        self.assertEqual(MISSING_START, ACQ_START_ISO)
        self.assertEqual(MISSING_START, "2023-02-26T15:40:00Z")
        self.assertEqual(MISSING_END, "2026-07-23T01:00:59Z")
        self.assertEqual(OUTLIER_TS, "2026-01-21T15:40:00Z")
        self.assertTrue(MISSING_START <= OUTLIER_TS <= MISSING_END)
        self.assertEqual(ACQ_END_ISO, "2026-09-07T20:10:00Z")

    def test_catalog_rejects_generic_and_keeps_broker_partial(self) -> None:
        cat = {r["SOURCE_NAME"]: r for r in source_catalog()}
        self.assertEqual(cat["DUKASCOPY_XAUUSD_TICKS"]["CANONICAL_STATUS"], "REJECTED")
        self.assertEqual(cat["HISTDATA_XAUUSD"]["CANONICAL_STATUS"], "REJECTED")
        self.assertEqual(cat["MT5_TESTER_GENERATED_TICKS"]["CANONICAL_STATUS"], "REJECTED")
        self.assertEqual(cat["PHASE118_OPERATOR_EXPORT"]["CANONICAL_STATUS"], "PARTIAL")
        self.assertEqual(cat["LITEFINANCE_SUPPORT_HISTORICAL_ARCHIVE"]["CANONICAL_STATUS"], "UNKNOWN")

    def test_support_template(self) -> None:
        tpl = support_request_template()
        self.assertFalse(tpl["submitted_by_this_phase"])
        self.assertIn("XAUUSD_i", tpl["body"])
        self.assertIn(OUTLIER_TS, tpl["body"])
        self.assertIn(ACQ_START_ISO, tpl["body"])
        self.assertIn(ACQ_END_ISO, tpl["body"])


class TestPhase119Collection(unittest.TestCase):
    def test_artifact_statuses(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE119_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["PHASE119_STATUS"], "PASS")
        self.assertEqual(payload["SOURCE_RESEARCH_STATUS"], "COMPLETE")
        self.assertFalse(payload["CANONICAL_SOURCE_AVAILABLE"])
        self.assertFalse(payload["CANONICAL_EQUIVALENCE_PROVEN"])
        self.assertEqual(payload["FULL_HORIZON_SOURCE_STATUS"], "MISSING")
        self.assertFalse(payload["OUTLIER_31_84R_COVERAGE"])
        self.assertEqual(payload["ACQUISITION_STATUS"], "OPERATOR_CONTACT_REQUIRED")
        self.assertTrue(payload["OPERATOR_ACTION_REQUIRED"])
        self.assertEqual(payload["NEXT_ACTION"], "REQUEST_LITEFINANCE_XAUUSD_I_HISTORICAL_TICK_DUMP")
        self.assertFalse(payload["DATA_ACQUIRED"])
        self.assertFalse(payload["MT5_USED"])
        self.assertFalse(payload["ENV_ACCESSED"])
        self.assertFalse(payload["EXIT_DESIGN_SPEC_IMPLEMENTED"])
        self.assertFalse(payload["PRODUCTION_CHANGED"])
        self.assertTrue(payload["phase118_raw_untouched"]["matches_phase118"])
        self.assertEqual(payload["RAW_DATA_HASH"], EXPECTED_RAW_SHA256)

    def test_frozen_and_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE119_JSON).read_text(encoding="utf-8"))
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertEqual(file_sha256(root / PHASE40_SETUPS_JSONL), EXPECTED_JSONL_SHA256)
        self.assertEqual(payload["FROZEN_PHASE40_TIMESTAMP"], PHASE40_TS)
        self.assertEqual(payload["FROZEN_PHASE40_FINGERPRINT"], FROZEN)
        self.assertEqual(payload["FROZEN_PHASE40_SHA256"], EXPECTED_JSONL_SHA256)
        self.assertIn("PHASE119_STATUS", (root / PHASE119_MD).read_text(encoding="utf-8"))
        self.assertIn("H119-01", (root / LEDGER_MD).read_text(encoding="utf-8"))
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 119 started | **YES** |", ku)
        self.assertIn("| Phase 120 started | **YES** |", ku)
        self.assertIn("| Phase 121 started | **YES** |", ku)
        self.assertIn("| Phase 122 started | **YES** |", ku)
        self.assertIn("| Phase 123 started | **YES** |", ku)
        self.assertIn("| Phase 124 started | **NO** |", ku)
        src = (root / "tradingbot/backtest/phase119_historical_tick_recovery.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()