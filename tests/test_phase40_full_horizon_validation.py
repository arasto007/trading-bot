"""Phase 40 — full-horizon unchanged strategy validation tests."""

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
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import PHASE38_M5
from tradingbot.backtest.phase40_full_horizon_validation import (
    BLOCKED,
    PHASE,
    PHASE40_JSON,
    PHASE40_MD,
    PHASE40_SETUPS_JSONL,
    REQUIRED_ARTIFACT_KEYS,
    ROBUSTNESS_DECLARATION,
    SCAN_WINDOW_BARS,
    SENSITIVITY_DECLARATION,
    WALKFORWARD_DECLARATION,
    run_phase40_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "get_mt5_credentials",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = root / PHASE40_JSON
    tape = root / PHASE38_M5
    if artifact.is_file() and tape.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        scan = payload.get("scan") or {}
        if (
            payload.get("fingerprints", {}).get("phase28_m5_unchanged")
            and scan.get("completed") is True
            and int(scan.get("tape_rows_loaded") or 0) >= 250_000
            and scan.get("horizon_shortened") is False
            and scan.get("sampled") is False
            and (root / PHASE40_SETUPS_JSONL).is_file()
        ):
            return
    run_phase40_collection(root)


class TestPhase40FullHorizonValidation(unittest.TestCase):
    def test_frozen_tape_full_scan_and_no_silent_map(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertTrue(payload["fingerprints"]["phase28_m5_unchanged"])
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertTrue(payload["dataset_binding"]["empty_map"])
        self.assertFalse(payload["dataset_binding"]["xauusd_merged"])
        self.assertFalse(payload["dataset_binding"]["logical_xauusd_used"])
        self.assertEqual(payload["ev_eq_01"], "NOT_PROVEN")
        self.assertNotEqual(PHASE38_M5, CANONICAL_PARQUET)
        scan = payload["scan"]
        self.assertTrue(scan["completed"])
        self.assertEqual(int(scan["tape_rows_loaded"]), 250_000)
        self.assertFalse(scan["horizon_shortened"])
        self.assertFalse(scan["sampled"])
        self.assertFalse(scan["random_sample"])
        self.assertEqual(int(scan["window_bars"]), SCAN_WINDOW_BARS)
        self.assertTrue(scan["closed_bar_only"])
        self.assertTrue(scan["same_bar_sl_before_tp"])
        self.assertGreaterEqual(int((payload.get("events") or {}).get("event_count") or 0), 30)
        self.assertEqual((payload.get("raw_performance") or {}).get("label"), "RAW_THEORETICAL")
        self.assertIn(payload["classification"]["strategy_raw_evidence"], {"A", "B", "C", "D"})
        self.assertIn(payload["classification"]["broker_realistic_evidence"], {"A", "B", "C", "D"})
        self.assertIn(payload["classification"]["overall"], {"A", "B", "C", "D"})
        self.assertEqual(payload["classification"]["profitability_verdict"], "NOT_ISSUED")
        self.assertFalse(payload["cost_completeness"]["gate_weakened"])
        self.assertFalse(payload["cost_completeness"]["cost_ready_for_validation"])
        self.assertEqual(payload["cost_completeness"]["complete_count"], 0)
        self.assertEqual(payload["cost_sensitivity"]["commission"], "UNKNOWN")
        self.assertTrue(WALKFORWARD_DECLARATION["declared_before_metrics"])
        self.assertFalse(WALKFORWARD_DECLARATION["shuffle"])
        self.assertTrue(SENSITIVITY_DECLARATION["declared_before_metrics"])
        self.assertTrue(ROBUSTNESS_DECLARATION["declared_before_metrics"])
        self.assertFalse(ROBUSTNESS_DECLARATION["optimization"])
        self.assertFalse(payload["robustness"]["selected_as_preferred"])
        exe = payload["executable"]
        self.assertFalse(exe.get("mixed_with_raw"))
        self.assertFalse(exe.get("fills_fabricated"))
        self.assertEqual(exe.get("status"), "EXECUTABLE_BLOCKED_BY_UNKNOWN_COMMISSION")
        attr = set((exe.get("reject_attribution") or {}).keys())
        self.assertTrue(attr <= {"META", "ATR", "LOT", "SPREAD", "NEWS", "COOLDOWN", "OTHER", "ALLOWED"})
        matrix = {row["Requirement"]: row for row in payload["blocker_matrix"]}
        self.assertIn("M5 horizon", matrix)
        self.assertIn("strategy evidence classification", matrix)

    def test_safety_no_env_no_phase_41(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE40_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["safety"]["BOT_STARTED"])
        self.assertFalse(payload["safety"]["ORDERS_SENT"])
        self.assertFalse(payload["safety"]["SYMBOL_SELECT"])
        self.assertFalse(payload["phase_41_started"])
        self.assertEqual(payload["production_changes"], "NONE")
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        self.assertFalse(payload["parameters_optimized"])
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotRegex(raw.lower(), rf'"{secret}"\s*:')
        src = (root / "tradingbot" / "backtest" / "phase40_full_horizon_validation.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        self.assertNotIn("phase41_", src.lower())
        md = (root / PHASE40_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 40", md)
        self.assertIn("DO NOT START PHASE 41", md)
        self.assertIn("does **not** issue a profitability verdict", md)
        self.assertTrue((root / PHASE40_SETUPS_JSONL).is_file())
        self.assertFalse((payload.get("research") or {}).get("optimized", True))
        self.assertFalse((payload.get("research") or {}).get("logical_xauusd_used", True))
