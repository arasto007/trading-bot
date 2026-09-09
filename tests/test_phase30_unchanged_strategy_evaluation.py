"""Phase 30 — unchanged strategy evaluation tests."""

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
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import (
    BLOCKED,
    PHASE,
    PHASE30_JSON,
    PHASE30_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase30_collection,
    strategy_logic_fingerprint,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase30_collection(Path(__file__).resolve().parents[1])


class TestPhase30UnchangedStrategy(unittest.TestCase):
    def test_frozen_tape_and_unchanged_strategy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE30_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertFalse(payload["logical_xauusd_used"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["parameters_searched"])
        self.assertFalse(payload["strategy_changed"])
        self.assertFalse(payload["riskgate_changed"])
        self.assertTrue(payload["research_configuration"]["unchanged_from_production_preset"])
        self.assertEqual(
            payload["research_configuration"]["strategy_logic_fingerprint"],
            strategy_logic_fingerprint(),
        )
        self.assertEqual(payload["research_configuration"]["dataset_symbol_map"], {})

    def test_separate_books_event_level_and_costs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE30_JSON).read_text(encoding="utf-8"))
        raw = payload["raw_signal_book"]
        self.assertEqual(raw["n"], 24)
        self.assertEqual(len(raw["rows"]), 24)
        self.assertIn("signal_id", raw["rows"][0])
        self.assertIn("event_cluster_id", raw["rows"][0])
        self.assertLess(payload["event_level"]["n_events"], 24)
        self.assertGreaterEqual(payload["event_level"]["n_events"], 1)
        exe = payload["executable_book"]
        self.assertEqual(exe["candidates"], 24)
        self.assertEqual(exe["allowed"], 0)
        self.assertEqual(exe["attribution"].get("META"), 18)
        self.assertEqual(exe["attribution"].get("ATR"), 6)
        self.assertEqual(payload["filled_book"]["n"], 0)
        self.assertEqual(payload["filled_book"]["status"], "NOT_OBSERVED")
        self.assertEqual(payload["cost_book"]["COST_ADJUSTED_R"]["label"], "MODELED")
        self.assertTrue(payload["cost_book"]["COST_ADJUSTED_R"]["not_realized"])
        self.assertEqual(payload["cost_book"]["COST_ADJUSTED_R"]["components"]["commission"], "UNKNOWN")
        self.assertEqual(payload["cost_book"]["GROSS_R"]["components"]["spread"], "NOT_APPLIED")
        p281 = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        self.assertEqual(raw["performance"]["wins"], 1)
        self.assertEqual(raw["performance"]["losses"], 23)
        self.assertEqual(
            [r["timestamp"] for r in raw["rows"]],
            [r["timestamp"] for r in (p281.get("raw_signal") or {}).get("setup_rows") or []],
        )

    def test_indeterminate_reproducible_no_phase_31(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE30_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["statistical_sufficiency"]["classification"], "DATA_INSUFFICIENT")
        self.assertEqual(payload["conclusion"]["verdict"], "INDETERMINATE")
        self.assertFalse(payload["conclusion"]["edge_supported"])
        self.assertFalse(payload["conclusion"]["no_edge_supported"])
        self.assertTrue(payload["reproducibility"]["passes_match"])
        self.assertEqual(payload["reproducibility"]["passes"], 2)
        self.assertTrue(payload["lookahead"]["official_results_closed_bars_only"])
        self.assertFalse(payload["lookahead"]["precedence_changed"])
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_31_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase30_unchanged_strategy_evaluation.py").read_text(
            encoding="utf-8"
        )
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE30_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 30", md)
        self.assertIn("DO NOT START PHASE 31", md)
        self.assertIn("INDETERMINATE", md)
        self.assertNotIn("phase31_", src.lower())
