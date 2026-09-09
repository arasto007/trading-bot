"""Phase 36 — strategy evidence verdict tests."""

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
from tradingbot.backtest.phase36_strategy_verdict import (
    ALLOWED_VERDICTS,
    BLOCKED,
    HIERARCHY_LEVELS,
    PHASE,
    PHASE36_JSON,
    PHASE36_MD,
    REQUIRED_ARTIFACT_KEYS,
    SOURCE_ARTIFACTS,
    VERDICT_A,
    VERDICT_B,
    VERDICT_C,
    VERDICT_D,
    run_phase36_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    "bounded_readonly_attach_once",
    'Path(".env")',
)
PRODUCTION_MUST_STAY = (
    "engine/strategies/price_action_strategy.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/config/pa_symbol_tf_presets.py",
    "tradingbot/config/live.py",
    "tradingbot/domain/gold_strategies/m5_london_sweep.py",
)


def setUpModule() -> None:
    run_phase36_collection(Path(__file__).resolve().parents[1])


class TestPhase36StrategyVerdict(unittest.TestCase):
    def test_verdict_insufficient_and_frozen_tape(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE36_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["parameters_searched"])
        self.assertFalse(payload["production_changed"])
        self.assertFalse(payload["optimization_phase"])
        self.assertFalse(payload["live_orders"])
        self.assertEqual(payload["strategy_verdict"]["code"], VERDICT_D)
        self.assertIn(payload["strategy_verdict"]["code"], ALLOWED_VERDICTS)
        self.assertNotEqual(payload["strategy_verdict"]["code"], VERDICT_A)
        self.assertNotEqual(payload["strategy_verdict"]["code"], VERDICT_C)
        self.assertNotEqual(payload["strategy_verdict"]["code"], VERDICT_B)
        self.assertFalse(payload["strategy_verdict"]["edge_exists_claim"])
        self.assertFalse(payload["strategy_verdict"]["no_edge_exists_claim"])
        self.assertTrue(payload["strategy_verdict"]["theoretical_is_not_live"])
        self.assertFalse(payload["strategy_verdict"]["strong_positive_edge_evidence"])
        self.assertFalse(payload["strategy_verdict"]["strong_no_edge_evidence"])
        self.assertFalse(payload["sample_sufficient"])
        self.assertFalse(payload["cost_complete"])
        self.assertEqual(payload["canonical_code"]["preset"], "gold_ny_sweep")
        self.assertEqual(payload["canonical_code"]["primary_symbol"], "XAUUSD_i")
        self.assertFalse(payload["canonical_code"]["production_files_modified_this_phase"])
        for name in SOURCE_ARTIFACTS:
            self.assertIn(name, payload["evidence_sources"])
        for level in HIERARCHY_LEVELS:
            self.assertIn(level, payload["evidence_hierarchy"])
            self.assertGreaterEqual(len(payload["evidence_hierarchy"][level]), 1)
        for key in (
            "strategy_signal_quality",
            "riskgate_behavior",
            "execution_behavior",
            "broker_costs",
            "data_quality",
            "sample_sufficiency",
        ):
            self.assertIn(key, payload["distinctions"])
        self.assertFalse(payload["distinctions"]["strategy_signal_quality"]["blame_riskgate"])
        self.assertFalse(payload["distinctions"]["riskgate_behavior"]["blame_strategy_for_rejects"])
        self.assertFalse(payload["cause_review"]["optimization_supported"])
        self.assertGreaterEqual(len(payload["missing_evidence"]), 3)
        self.assertEqual(payload["evidence_sources"]["phase28_4"]["official_answer"], "J")
        self.assertEqual(payload["evidence_sources"]["phase31"]["events"], 6)
        self.assertEqual(payload["evidence_sources"]["phase35"]["cost_completeness"], "INCOMPLETE")

    def test_production_blocked_no_phase_37(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE36_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_37_started"])
        self.assertFalse(payload["research_decision"]["optimize_production"])
        self.assertFalse(payload["research_decision"]["change_production"])
        self.assertFalse(payload["research_decision"]["start_another_phase_automatically"])
        self.assertFalse(payload["research_decision"]["re_audit_same_15_day_book"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        self.assertTrue(payload["reproducibility"]["passes_match"])
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase36_strategy_verdict.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE36_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 36", md)
        self.assertIn("DO NOT START PHASE 37", md)
        self.assertIn("INSUFFICIENT_EVIDENCE", md)
        self.assertIn("DO NOT OPTIMIZE", md)
        self.assertNotIn("phase37_", src.lower())
        for rel in PRODUCTION_MUST_STAY:
            self.assertTrue((root / rel).is_file())
        sot = (root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md").read_text(encoding="utf-8")
        self.assertIn("PHASE36_STRATEGY_VERDICT.md", sot)
        self.assertIn("INSUFFICIENT_EVIDENCE", sot)
