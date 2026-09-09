"""Phase 28.4 — strategy diagnosis tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
)
from tradingbot.backtest.phase28_1_full_baseline import PHASE281_JSON
from tradingbot.backtest.phase28_3_monte_carlo import PHASE283_JSON
from tradingbot.backtest.phase28_4_strategy_diagnosis import (
    BLOCKED,
    PHASE,
    PHASE284_JSON,
    PHASE284_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase28_4_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase28_4_collection(Path(__file__).resolve().parents[1])


class TestPhase284StrategyDiagnosis(unittest.TestCase):
    def test_reconstructs_stored_setups_fingerprint_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE284_JSON).read_text(encoding="utf-8"))
        p281 = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertEqual(payload["raw_setups"], 24)
        self.assertEqual(len(payload["reconstructed_setups"]), 24)
        self.assertEqual(payload["buy"], 16)
        self.assertEqual(payload["sell"], 8)
        self.assertEqual(payload["wins"], 1)
        self.assertEqual(payload["losses"], 23)
        stored_ts = [
            r["timestamp"]
            for r in (p281.get("raw_signal") or {}).get("setup_rows") or []
        ]
        got_ts = [r["timestamp"] for r in payload["reconstructed_setups"]]
        self.assertEqual(got_ts, stored_ts)
        self.assertTrue(all(r["session_context"]["in_configured_window"] for r in payload["reconstructed_setups"]))
        self.assertTrue(payload["session_diagnosis"]["all_24_inside_hour_15"])

    def test_diagnoses_and_overlap_without_optimization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE284_JSON).read_text(encoding="utf-8"))
        for key in (
            "entry_diagnosis",
            "sl_diagnosis",
            "tp_diagnosis",
            "session_diagnosis",
            "regime_diagnosis",
            "signal_quality_diagnosis",
            "overlap_diagnosis",
        ):
            self.assertIn(key, payload)
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["parameters_searched"])
        self.assertFalse(payload["strategy_changed"])
        self.assertFalse(payload["riskgate_changed"])
        self.assertFalse(payload["rr_changed"])
        self.assertEqual(payload["entry_diagnosis"]["class"], "ANALYTICAL_COUNTERFACTUAL_ONLY")
        self.assertFalse(payload["entry_diagnosis"]["production_strategy_altered"])
        ov = payload["overlap_diagnosis"]
        self.assertLess(ov["n_event_clusters"], 24)
        self.assertTrue(ov["do_not_treat_as_24_independent"])
        self.assertGreaterEqual(ov["n_clustered_setups"], 1)
        self.assertFalse(payload["riskgate_status"]["bypassed"])
        self.assertEqual(payload["riskgate_status"]["allowed"], 0)
        self.assertEqual(payload["riskgate_status"]["fills"], 0)

    def test_ranking_and_no_phase_28_5(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE284_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        rank = payload["root_cause_ranking"]
        self.assertEqual(rank["PRIMARY"]["code"], "G")
        self.assertEqual(rank["SECONDARY"]["code"], "H")
        self.assertEqual(rank["TERTIARY"]["code"], "I")
        self.assertEqual(rank["official_answer_to_primary_question"], "J")
        self.assertIn("NOT_PROVEN", payload["what_is_not_proven"])
        self.assertIn("insufficient", payload["what_is_proven"].lower())
        self.assertEqual(payload["evidence_confidence"]["strategy_is_bad"], "NOT_ALLOWED")
        self.assertEqual(payload["evidence_confidence"]["strategy_is_good"], "NOT_ALLOWED")
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_28_5_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        p283 = json.loads((root / PHASE283_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["prior_phase_28_3_conclusion"], p283["conclusion"])
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase28_4_strategy_diagnosis.py").read_text(
            encoding="utf-8"
        )
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE284_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 28.4", md)
        self.assertIn("DO NOT START PHASE 28.5", md)
        self.assertIn("ANALYTICAL", md)
        self.assertNotIn("phase28_5", src.lower())
