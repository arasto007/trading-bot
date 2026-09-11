"""Phase 29 — long-horizon XAUUSD_i research tape tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    load_parquet_utc,
)
from tradingbot.backtest.phase29_research_tape import (
    BLOCKED,
    PHASE,
    PHASE29_JSON,
    PHASE29_MD,
    REQUIRED_ARTIFACT_KEYS,
    content_fingerprint,
    run_phase29_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase29_collection(Path(__file__).resolve().parents[1])


class TestPhase29ResearchTape(unittest.TestCase):
    def test_frozen_canonical_unchanged_and_no_silent_map(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE29_JSON).read_text(encoding="utf-8"))
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(payload["fingerprints"]["phase28_m5_file"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertTrue(payload["fingerprints"]["phase28_m5_unchanged"])
        self.assertFalse(payload["canonical_m5_changed"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertFalse(payload["datasets"]["logical_xauusd_used"])
        self.assertTrue(payload["dataset_binding"]["empty_map"])
        self.assertFalse(payload["dataset_binding"]["xauusd_merged"])
        self.assertEqual(payload["dataset_binding"]["m5"]["binding"]["mapping_status"], "MATCH")
        self.assertEqual(payload["ev_eq_01"], "NOT_PROVEN")
        df = load_parquet_utc(root / CANONICAL_PARQUET)
        self.assertEqual(content_fingerprint(df), payload["fingerprints"]["phase28_m5_content"])
        self.assertEqual(content_fingerprint(df), content_fingerprint(df))

    def test_honest_coverage_and_bidask_labels(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE29_JSON).read_text(encoding="utf-8"))
        m5 = payload["dataset_coverage"]["m5"]
        # Frozen Phase 28 canonical window remains short (<60d) and is not overwritten.
        self.assertLess(float(m5["days"]), 60.0)
        self.assertTrue(m5["below_minimum_60d"])
        self.assertEqual(m5["bars"], 3000)
        # Phase 29 status tracks the longest *persisted* XAUUSD_i research tape.
        # data/XAUUSD_i_5m_phase29.parquet covers >=180d → PASS (not PASS_WITH_DEFERRAL).
        # This is not a bid/ask gate loosening; spread COMPLETE still requires full-horizon M5.
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["production_changes"], "NONE")
        self.assertFalse(payload["parameters_optimized"])
        ba = payload["bid_ask"]
        self.assertFalse(ba["in_ohlc_parquet"])
        self.assertEqual(ba["ohlc_spread_status"], "PROXY")
        if ba["available"]:
            self.assertEqual(ba["spread_provenance"], "OBSERVED")
            self.assertTrue(ba["stats"]["not_proxy"])
            for key in ("median", "p50", "p75", "p90", "p95", "p99", "maximum"):
                self.assertIn(key, ba["stats"])
        q = payload["data_quality"]["m5"]
        for key in (
            "duplicate_timestamps",
            "malformed_ohlc",
            "impossible_ohlc",
            "zero_volume",
            "gap_classification",
        ):
            self.assertIn(key, q)
        self.assertEqual(q["duplicate_timestamps"], 0)
        self.assertEqual(q["impossible_ohlc"], 0)
        self.assertIn("EXPECTED_WEEKEND_GAP", q["gap_classification"])
        self.assertEqual(payload["collection"]["m5"]["status"], "NOT_OBSERVED")
        self.assertFalse(payload["collection"]["mt5_started_by_script"])
        self.assertFalse(payload["collection"]["symbol_select_called"])

    def test_gate_docs_and_no_phase_30(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE29_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_30_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase29_research_tape.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE29_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 29", md)
        self.assertIn("DO NOT START PHASE 30", md)
        self.assertIn("NOT_OBSERVED", md)
        self.assertNotIn("phase30_", src.lower().replace("phase30_started", ""))
        self.assertFalse(payload["safety"]["CANONICAL_M5_OVERWRITTEN"])
